import json
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import frappe

from rms.api.pos import cancel_confirmed_order_items, create_void_waste_stock_entry


class TestBatchItemCancellation(unittest.TestCase):
	def setUp(self):
		stack = ExitStack()
		self.addCleanup(stack.close)
		self.rows = [frappe._dict(name=f"ROW-{index}", qty=3, cancelled_qty=0, sent_to_kitchen=1, uom="Nos") for index in (1, 2)]
		self.order = SimpleNamespace(name="ORDER-1", store="STORE-1", status="Confirmed", cashier_session="SESSION-1",
			guest_checks=[], modified="2026-11-05 12:00:00", items=self.rows, subtotal=100, discount_amount=0, tax_total=14, grand_total=114)
		for target, kwargs in (
			("require_pos_action", {}), ("require_pos_role", {}),
			("get_pos_capabilities", {"return_value": {"can_void_items": True, "can_void_waste": True}}), ("assert_store_access", {}), ("require_order_scope", {}),
			("frappe.get_roles", {"return_value": ["POS Manager"]}),
			("frappe.db", {"new": MagicMock(), "create": True}),
			("frappe.get_doc", {"return_value": self.order}),
			("frappe.get_cached_value", {"return_value": 1}),
			("_cancel_confirmed_order_item", {}),
		):
			mock = stack.enter_context(patch(f"rms.api.pos.{target}", **kwargs))
			if target == "frappe.db": self.db = mock
			elif target == "frappe.get_doc": self.get_doc = mock
			elif target == "_cancel_confirmed_order_item": self.cancel = mock
		self.db.get_value.return_value = "SESSION-1"
		stack.enter_context(patch("rms.rms.doctype.pos_action_reason.pos_action_reason.validate_pos_action_reason", return_value="Customer request"))

	def run_batch(self, items=None, **kwargs):
		return cancel_confirmed_order_items("ORDER-1", items if items is not None else [
			{"item_name": "ROW-1", "qty": 1}, {"item_name": "ROW-2", "qty": 2}], "REASON-1", **kwargs)

	def test_batch_uses_one_reason_and_locks_the_order(self):
		result = self.run_batch(json.dumps([{"item_name": "ROW-1", "qty": 1}, {"item_name": "ROW-2", "qty": 2}]),
			expected_modified=self.order.modified)
		self.get_doc.assert_any_call("POS Order", "ORDER-1", for_update=True)
		self.assertEqual(self.cancel.call_args_list, [call("ORDER-1", "ROW-1", 1, "REASON-1", is_waste=0, comment="", authorization=self.authorization()), call("ORDER-1", "ROW-2", 2, "REASON-1", is_waste=0, comment="", authorization=self.authorization())])
		self.assertEqual(len(result["items"]), 2)
		self.db.savepoint.assert_called_once_with("rms_batch_item_cancellation")
		self.db.commit.assert_not_called()

	def test_every_quantity_is_validated_before_any_cancellation(self):
		for items in (
			[{"item_name": "ROW-1", "qty": 1}, {"item_name": "ROW-2", "qty": 4}],
			[{"item_name": "ROW-1", "qty": 1}, {"item_name": "OTHER", "qty": 1}],
			[{"item_name": "ROW-1", "qty": 1}, {"item_name": "ROW-1", "qty": 1}],
			[{"item_name": "ROW-1", "qty": 0.5}], [{"item_name": "ROW-1", "qty": float("nan")}],
			[], "invalid JSON",
		):
			with self.subTest(items=items), self.assertRaises(frappe.ValidationError):
				self.run_batch(items)
		self.cancel.assert_not_called()
		self.db.savepoint.assert_not_called()

	def test_waste_choice_reaches_each_cancellation(self):
		self.run_batch(is_waste="1")
		self.assertEqual(self.cancel.call_args_list, [call("ORDER-1", "ROW-1", 1, "REASON-1", is_waste=1, comment="", authorization=self.authorization()),
			call("ORDER-1", "ROW-2", 2, "REASON-1", is_waste=1, comment="", authorization=self.authorization())])

	def test_invalid_waste_option_does_not_mutate_order(self):
		with self.assertRaises(frappe.ValidationError): self.run_batch(is_waste="yes")
		self.cancel.assert_not_called()

	def test_waste_issues_only_voided_recipe_and_stock_modifier_quantities(self):
		self.order.order_type = "Takeaway"
		row = frappe._dict(name="ROW-1", selling_product="RECIPE", item="FINISHED", qty=4, uom="Nos", warehouse="WH",
			recipe_snapshot='[{"item":"RICE","qty":2,"uom":"Kg","warehouse":"WH"}]',
			modifiers='[{"modifier_product":"SAUCE","item":"SAUCE-STOCK","qty":2,"warehouse":"WH"}]')
		self.db.get_value.side_effect = lambda doctype, *args, **kwargs: {"Store":"COMPANY", "Order Type Account Mapping":"COGS", "Item":1 if args[-1] == "is_stock_item" else "Nos"}.get(doctype)
		with patch("rms.api.pos.frappe.get_cached_doc", side_effect=lambda doctype, name: frappe._dict(with_recipe=name == "RECIPE", maintain_stock=1)), \
				patch("rms.api.pos.create_material_issue", return_value="WASTE-STOCK-1") as issue:
			self.assertEqual(create_void_waste_stock_entry(self.order, row, 1, "Damaged"), "WASTE-STOCK-1")
		components = issue.call_args.args[1]
		self.assertEqual([(component['item'],component['qty']) for component in components], [("RICE", .5), ("SAUCE-STOCK", 2)])
		self.assertEqual(issue.call_args.args[0], "COMPANY")
		self.assertEqual(issue.call_args.args[2], "COGS")
		self.assertEqual(json.loads(row.recipe_snapshot)[0]['qty'],2,'the saved recipe snapshot remains unchanged')

	def test_failure_rolls_back_the_entire_batch(self):
		self.cancel.side_effect = [None, frappe.ValidationError("Kitchen update failed")]
		with self.assertRaisesRegex(frappe.ValidationError, "Kitchen update failed"):
			self.run_batch()
		self.db.rollback.assert_called_once_with(save_point="rms_batch_item_cancellation")

	def test_changed_order_rejects_the_stale_selection(self):
		with self.assertRaisesRegex(frappe.ValidationError, "order changed"):
			self.run_batch(expected_modified="2026-11-05 11:00:00")
		self.cancel.assert_not_called()

	def test_guest_checks_and_unsent_rows_are_protected(self):
		self.order.guest_checks = [SimpleNamespace(status="Open")]
		with self.assertRaises(frappe.ValidationError): self.run_batch()
		self.order.guest_checks = []
		self.rows[1].sent_to_kitchen = 0
		with self.assertRaises(frappe.ValidationError): self.run_batch()
		self.cancel.assert_not_called()

	def authorization(self):
		return dict(approved_by=frappe.session.user, approval_challenge=None)

	def test_cashier_without_permission_needs_manager_before_any_mutation(self):
		with patch("rms.api.pos.get_pos_capabilities", return_value={"can_void_items": False}), \
				patch("rms.pos_operation_approval.eligible_managers", return_value=[{"user": "manager@example.com"}]):
			result = self.run_batch()
		self.assertTrue(result["requires_manager_authorization"])
		self.cancel.assert_not_called()

	def test_store_and_order_scope_permissions_remain_required(self):
		for target in ("assert_store_access", "require_order_scope"):
			with patch(f"rms.api.pos.{target}", side_effect=frappe.PermissionError), self.assertRaises(frappe.PermissionError):
				self.run_batch()
		self.cancel.assert_not_called()
