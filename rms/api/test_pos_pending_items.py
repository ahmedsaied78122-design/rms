"""Pending additions stay editable after autosave on a confirmed order."""
import copy
import json
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import frappe

from rms.api.pos import save_order


class TestPendingOrderItems(unittest.TestCase):
	def order(self):
		doc = frappe.new_doc("POS Order")
		doc.update(dict(name="ORDER-1", store="STORE-1", cashier_session="SESSION-1", status="Confirmed",
			restaurant_brand="BRAND-1", order_type="Takeaway"))
		for name, sent in (("SENT-1", 1), ("PENDING-1", 0)):
			doc.append("items", dict(name=name, selling_product="TEA", qty=1, selling_price=10,
				amount=10, sent_to_kitchen=sent, modifiers="[]", recipe_snapshot="[]"))
		return doc

	def test_pending_quantity_and_removal_do_not_unlock_confirmed_rows(self):
		previous = self.order()
		current = copy.deepcopy(previous)
		current.items[1].qty = 4
		current.validate_pending_item_edit(previous)
		current.set("items", [current.items[0]])
		current.validate_pending_item_edit(previous)
		current.items[0].qty = 2
		with self.assertRaisesRegex(frappe.ValidationError, "Confirmed items cannot"):
			current.validate_pending_item_edit(previous)

	def test_sent_identity_and_confirmation_flag_are_protected(self):
		previous = self.order()
		for mutate in (lambda doc: setattr(doc.items[0], "name", "REPLACEMENT"),
			lambda doc: setattr(doc.items[0], "sent_to_kitchen", 0),
			lambda doc: setattr(doc.items[1], "sent_to_kitchen", 1)):
			current = copy.deepcopy(previous)
			mutate(current)
			with self.assertRaisesRegex(frappe.ValidationError, "Confirmed items cannot"):
				current.validate_pending_item_edit(previous)

	def test_guest_allocations_cannot_be_edited(self):
		previous = self.order()
		previous.append("guest_checks", {"name": "CHECK-1", "status": "Open"})
		with self.assertRaises(frappe.ValidationError):
			copy.deepcopy(previous).validate_pending_item_edit(previous)

	def save(self, doc, items):
		data = {field: doc.get(field) for field in ("store", "restaurant_brand", "order_type", "customer",
			"external_reference", "dining_area", "dining_table", "discount_type", "discount_scope", "discount_value", "discount_reason")}
		data.update(name=doc.name, edit_pending_items=True, items=items)
		session = frappe._dict(name="SESSION-1", status="Open", user=frappe.session.user)
		with ExitStack() as stack:
			for name, value in {"require_pos_action": None, "require_order_scope": None,
				"assert_store_access": frappe._dict(name=doc.store), "get_user_session": session,
				"get_brands": [{"name": doc.restaurant_brand}], "get_order_types": [{"name": doc.order_type}],
				"frappe.get_doc": doc}.items():
				stack.enter_context(patch("rms.api.pos." + name, return_value=value))
			stack.enter_context(patch.object(doc, "is_new", return_value=False))
			stack.enter_context(patch.object(doc, "save"))
			return save_order(json.dumps(data))

	def test_api_reuses_pending_identity_and_accepts_empty_pending_list(self):
		doc = self.order()
		result = self.save(doc, [{"order_item_name": "PENDING-1", "selling_product": "TEA", "qty": 3}])
		self.assertEqual([(row.name, row.qty) for row in doc.items], [("SENT-1", 1), ("PENDING-1", 3)])
		self.assertEqual(result["appended_items"][0]["name"], "PENDING-1")
		self.save(doc, [])
		self.assertEqual([row.name for row in doc.items], ["SENT-1"])

	def test_api_rejects_sent_and_foreign_row_ids(self):
		for name in ("SENT-1", "ANOTHER-ORDER-ITEM"):
			with self.assertRaisesRegex(frappe.ValidationError, "Only unconfirmed items"):
				self.save(self.order(), [{"order_item_name": name, "selling_product": "TEA", "qty": 3}])
