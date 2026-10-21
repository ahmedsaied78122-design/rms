import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe
import rms.rms.doctype.pos_order.pos_order as pos_order_module
from rms.rms.doctype.pos_order.pos_order import (
	POSOrder,
	calculate_discount_amount,
	calculate_order_item_amount,
	validate_modifier_group_selection,
	normalize_dining_context,
	ensure_order_items_append_only,
)

try:
	from rms.snapshots import parse_json_rows, serialize_json_rows
except ImportError:
	parse_json_rows = None
	serialize_json_rows = None


class TestPOSOrderEmbeddedDataSchema(unittest.TestCase):
	def test_single_choice_modifier_group_rejects_two_selected_options(self):
		with self.assertRaises(frappe.ValidationError):
			validate_modifier_group_selection([
				{"modifier_group": "Milk Choice", "modifier_product": "Whole Milk"},
				{"modifier_group": "Milk Choice", "modifier_product": "Fat-Free Milk"},
			], {"Milk Choice"})

	def test_single_choice_modifier_group_accepts_one_and_multi_choice_group_accepts_many(self):
		validate_modifier_group_selection([
			{"modifier_group": "Milk Choice", "modifier_product": "Whole Milk"},
			{"modifier_group": "Sauces", "modifier_product": "Tahini"},
			{"modifier_group": "Sauces", "modifier_product": "Chili Sauce"},
		], {"Milk Choice"})

	def test_pos_order_desk_form_is_read_only_and_preserves_the_audit_trail(self):
		meta = frappe.get_meta("POS Order")
		for fieldname in (
			"store", "restaurant_brand", "order_type", "sales_taxes_and_charges_template",
			"cashier_session", "customer", "external_reference", "dining_area", "dining_table",
			"business_date", "items", "discount_type", "discount_scope", "discount_value",
			"discount_amount", "discount_reason", "payments",
		):
			self.assertTrue(meta.get_field(fieldname).read_only, f"{fieldname} must be managed through POS")
		self.assertFalse(meta.allow_rename)
		self.assertTrue(meta.permissions[0].read)
		self.assertFalse(meta.permissions[0].write)
		self.assertFalse(meta.permissions[0].create)
		self.assertFalse(meta.permissions[0].delete)
		self.assertFalse(meta.permissions[0].get("import"))

	def test_non_table_order_types_clear_dining_area_and_table(self):
		self.assertEqual(normalize_dining_context(False, "MAIN-HALL", "TABLE-01"), (None, None))

	def test_table_order_types_keep_the_selected_table(self):
		self.assertEqual(normalize_dining_context(True, "MAIN-HALL", "TABLE-01"), ("MAIN-HALL", "TABLE-01"))

	def test_confirmed_order_accepts_only_appended_lines(self):
		previous = [{"name": "LINE-1", "qty": 1}, {"name": "LINE-2", "qty": 2}]
		current = previous + [{"name": "LINE-3", "qty": 1}]
		self.assertEqual(ensure_order_items_append_only(previous, current), current[-1:])

	def test_confirmed_order_rejects_edit_or_removal_of_existing_lines(self):
		previous = [{"name": "LINE-1", "qty": 1}]
		with self.assertRaisesRegex(frappe.ValidationError, "Confirmed items cannot be edited"):
			ensure_order_items_append_only(previous, [{"name": "LINE-1", "qty": 2}])

	def test_confirmed_item_cancellation_requires_policy_validation_and_tracks_remaining_quantity(self):
		active_qty = getattr(pos_order_module, "get_active_order_item_qty", None)
		validate = getattr(pos_order_module, "validate_confirmed_item_cancellation", None)
		self.assertTrue(callable(active_qty), "Active order item quantity helper is missing")
		self.assertTrue(callable(validate), "Confirmed item cancellation policy is missing")
		self.assertEqual(active_qty(2, 0.5), 1.5)
		self.assertEqual(active_qty(2, 2), 0)
		self.assertEqual(pos_order_module.calculate_order_item_amount(2, 100, [frappe._dict(qty=1, selling_price=10)], 0.5), 165)
		self.assertEqual(validate("Ready", 1, 2, 0, 1, "Customer changed mind", True), 1)
		with self.assertRaisesRegex(frappe.PermissionError, "POS Manager"):
			validate("Ready", 1, 2, 0, 1, "Customer changed mind", False)
		with self.assertRaisesRegex(frappe.ValidationError, "reason"):
			validate("Ready", 1, 2, 0, 1, "  ", True)
		with self.assertRaisesRegex(frappe.ValidationError, "remaining quantity"):
			validate("Ready", 1, 2, 0.5, 2, "Customer changed mind", True)
		with self.assertRaisesRegex(frappe.ValidationError, "sent to preparation"):
			validate("Ready", 0, 2, 0, 1, "Customer changed mind", True)

	def test_item_cancellation_requires_matching_append_only_audit_event(self):
		protected = {"selling_product": "PRODUCT-1", "option_parent": None, "item": "ITEM-1", "qty": 2,
			"uom": "Nos", "selling_price": 100, "price_list": "Standard Selling", "warehouse": "Main",
			"preparation_area": "Kitchen", "notes": None, "modifiers": "[]", "recipe_snapshot": "[]", "sent_to_kitchen": 1}
		previous_row = frappe._dict(name="ROW-1", cancelled_qty=0, **protected)
		current_row = frappe._dict(name="ROW-1", cancelled_qty=1, **protected)
		event = frappe._dict(pos_order_item="ROW-1", qty=1, reason="Customer changed mind",
			cancelled_by=frappe.session.user, cancelled_at="2026-10-20 12:00:00")
		previous = SimpleNamespace(status="Ready", items=[previous_row], item_cancellations=[])
		order = frappe.new_doc("POS Order")
		order.items = [current_row]
		order.item_cancellations = [event]
		with patch("frappe.get_roles", return_value=["POS Manager"]):
			order.validate_item_cancellation_change(previous)
		event.qty = 0.5
		with patch("frappe.get_roles", return_value=["POS Manager"]):
			with self.assertRaisesRegex(frappe.ValidationError, "match the append-only"):
				order.validate_item_cancellation_change(previous)

	def test_new_order_inherits_open_cashier_session_business_date(self):
		order = frappe.new_doc("POS Order")
		order.store = "STORE-1"
		order.cashier_session = "SESSION-1"
		with patch("frappe.db.get_value", return_value="2026-10-19") as get_value, \
				patch("rms.rms.doctype.pos_order.pos_order.get_business_date", return_value="2026-10-20"):
			order.before_insert()
		self.assertEqual(order.business_date, "2026-10-19")
		get_value.assert_called_once_with("Cashier Session", "SESSION-1", "business_date")

	def test_open_order_validation_resolves_items_without_missing_total_method(self):
		order = frappe.new_doc("POS Order")
		order.status = "Open"
		with patch.object(order, "validate_context"), patch.object(order, "resolve_items"), \
				patch.object(order, "validate_payment_state"):
			order.validate()

	def test_kitchen_status_update_saves_with_internal_permissions(self):
		order = frappe.new_doc("POS Order")
		order.status = "Confirmed"
		with patch.object(order, "save") as save:
			order.set_kitchen_status("In Preparation")
		save.assert_called_once_with(ignore_permissions=True)

	def test_paid_order_rejects_payment_total_that_does_not_match_invoice_total(self):
		order = SimpleNamespace(status="Paid", grand_total=100,
			payments=[frappe._dict(amount=60), frappe._dict(amount=30)])
		with self.assertRaisesRegex(frappe.ValidationError, "Payment amounts must equal the order Grand Total"):
			POSOrder.validate_payment_state(order)

	def test_paid_order_accepts_exact_total_across_multiple_payment_methods(self):
		order = SimpleNamespace(status="Paid", grand_total=100,
			payments=[frappe._dict(mode_of_payment="Cash", amount=40), frappe._dict(mode_of_payment="Credit Card", amount=60)])
		POSOrder.validate_payment_state(order)

	def test_fully_discounted_paid_order_accepts_zero_tender_payment_row(self):
		order = SimpleNamespace(status="Paid", grand_total=0,
			payments=[frappe._dict(mode_of_payment="Cash", amount=0)])
		POSOrder.validate_payment_state(order)

	def test_unpaid_order_does_not_require_payment_rows(self):
		order = SimpleNamespace(status="Confirmed", grand_total=100, payments=[])
		POSOrder.validate_payment_state(order)

	def test_modifier_amount_scales_with_order_quantity(self):
		self.assertEqual(calculate_order_item_amount(2, 112, [frappe._dict(qty=1, selling_price=12)]), 248)

	def test_percentage_discount_can_apply_to_net_total_or_grand_total(self):
		self.assertEqual(calculate_discount_amount(100, 14, "Percentage", 10, "Net Total"), 10)
		self.assertEqual(calculate_discount_amount(100, 14, "Percentage", 10, "Grand Total"), 11.4)

	def test_fixed_discount_is_capped_at_its_selected_base(self):
		self.assertEqual(calculate_discount_amount(100, 14, "Amount", 120, "Grand Total"), 114)

	def test_cashier_discount_must_stay_within_pos_user_limit(self):
		order = frappe.new_doc("POS Order")
		order.discount_type = "Percentage"
		order.discount_scope = "Net Total"
		order.discount_value = 11
		order.discount_reason = "Customer recovery"
		with patch("frappe.get_roles", return_value=["POS Cashier"]), \
				patch("frappe.db.get_value", return_value=frappe._dict(can_apply_manual_discount=1, max_manual_discount_percent=10)):
			with self.assertRaisesRegex(frappe.ValidationError, "limited to a 10.0% discount"):
				POSOrder.validate_discount(order, 100, 14, 114)

	def test_explicit_pos_user_limit_applies_to_system_manager_cashier(self):
		order = frappe.new_doc("POS Order")
		order.discount_type = "Percentage"
		order.discount_scope = "Net Total"
		order.discount_value = 55
		order.discount_reason = "Approval test"
		with patch("frappe.get_roles", return_value=["System Manager"]), \
				patch("frappe.db.get_value", return_value=frappe._dict(can_apply_manual_discount=1, max_manual_discount_percent=50)):
			with self.assertRaisesRegex(frappe.ValidationError, "limited to a 50.0% discount"):
				POSOrder.validate_discount(order, 100, 14, 114)

	def test_cashier_discount_can_exceed_limit_with_server_verified_approval_flag(self):
		order = frappe.new_doc("POS Order")
		order.discount_type = "Percentage"
		order.discount_scope = "Net Total"
		order.discount_value = 25
		order.discount_reason = "Customer recovery"
		order.flags.discount_approval_authorized = True
		with patch("frappe.get_roles", return_value=["POS Cashier"]), \
				patch("frappe.db.get_value", return_value=frappe._dict(can_apply_manual_discount=1, max_manual_discount_percent=10)):
			POSOrder.validate_discount(order, 100, 14, 114)

	def test_pos_user_can_disable_manual_discounts(self):
		order = frappe.new_doc("POS Order")
		order.discount_type = "Percentage"
		order.discount_scope = "Net Total"
		order.discount_value = 5
		order.discount_reason = "Launch offer"
		with patch("frappe.get_roles", return_value=["POS Cashier"]), \
				patch("frappe.db.get_value", return_value=frappe._dict(can_apply_manual_discount=0, max_manual_discount_percent=10)):
			with self.assertRaisesRegex(frappe.PermissionError, "do not allow manual discounts"):
				POSOrder.validate_discount(order, 100, 14, 114)

	def test_recipe_snapshot_does_not_use_a_nested_child_table(self):
		field = frappe.get_meta("POS Order Item").get_field("recipe_snapshot")
		self.assertNotEqual(field.fieldtype, "Table")
		self.assertEqual(frappe.get_meta("POS Order Item").get_field("sent_to_kitchen").fieldtype, "Check")

	def test_modifiers_do_not_use_a_nested_child_table(self):
		field = frappe.get_meta("POS Order Item").get_field("modifiers")
		self.assertNotEqual(field.fieldtype, "Table")

	def test_json_rows_round_trip_unicode_and_nested_values(self):
		self.assertTrue(callable(parse_json_rows), "JSON snapshot parser is not implemented")
		self.assertTrue(callable(serialize_json_rows), "JSON snapshot serializer is not implemented")
		rows = [{"item": "مكون, خاص", "qty": 1.25, "meta": {"source": "recipe"}}]
		self.assertEqual(parse_json_rows(serialize_json_rows(rows)), rows)

	def test_invalid_json_snapshot_is_rejected(self):
		self.assertTrue(callable(parse_json_rows), "JSON snapshot parser is not implemented")
		with self.assertRaisesRegex(frappe.ValidationError, "invalid saved data"):
			parse_json_rows("{bad json")

	def test_order_item_stores_modifier_and_recipe_snapshots_without_nested_rows(self):
		order = frappe.new_doc("POS Order")
		row = order.append("items", {"selling_product": "DRAFT-PRODUCT"})
		row.modifiers = serialize_json_rows([{"modifier_product": "DRAFT-ADDON", "qty": 2}])
		row.recipe_snapshot = serialize_json_rows([{"item": "DRAFT-INGREDIENT", "qty": 0.5}])
		self.assertEqual(parse_json_rows(row.modifiers)[0].qty, 2)
		self.assertEqual(parse_json_rows(row.recipe_snapshot)[0].item, "DRAFT-INGREDIENT")

	def test_multiple_checks_share_a_table_only_when_they_share_the_server_group(self):
		order = SimpleNamespace(name="ORDER-2", dining_table="TABLE-1", table_check_group="CHECK-GROUP-1", check_label="Guest 2")
		with patch("frappe.get_all", return_value=[frappe._dict(name="ORDER-1", table_check_group="CHECK-GROUP-1", check_label="Guest 1")]):
			POSOrder.validate_table_check_occupancy(order)

	def test_same_table_checks_reject_duplicate_guest_labels_case_insensitively(self):
		order = SimpleNamespace(name="ORDER-2", dining_table="TABLE-1", table_check_group="CHECK-GROUP-1", check_label="  guest 1 ")
		with patch("frappe.get_all", return_value=[frappe._dict(name="ORDER-1", table_check_group="CHECK-GROUP-1", check_label="Guest 1")]):
			with self.assertRaisesRegex(frappe.ValidationError, "Check label is already used"):
				POSOrder.validate_table_check_occupancy(order)

	def test_unrelated_open_order_still_locks_the_table(self):
		order = SimpleNamespace(name="ORDER-2", dining_table="TABLE-1", table_check_group="CHECK-GROUP-2")
		with patch("frappe.get_all", return_value=[frappe._dict(name="ORDER-1", table_check_group="CHECK-GROUP-1")]):
			with self.assertRaisesRegex(frappe.ValidationError, "Use Split into checks"):
				POSOrder.validate_table_check_occupancy(order)

	def test_recipe_and_modifier_components_append_to_the_json_snapshot(self):
		order = frappe.new_doc("POS Order")
		row = order.append("items", {"qty": 2})
		with patch(
			"rms.rms.doctype.pos_order.pos_order.get_recipe_components",
			return_value=[{"item": "BASE-INGREDIENT", "qty": 1, "uom": "Nos", "warehouse": "Main"}],
		):
			POSOrder.build_recipe_snapshot(order, row, SimpleNamespace(name="BASE-PRODUCT"), "Main")
		with patch(
			"rms.rms.doctype.pos_order.pos_order.get_recipe_components",
			return_value=[{"item": "ADDON-INGREDIENT", "qty": 0.5, "uom": "Nos", "warehouse": "Main"}],
		):
			POSOrder.append_modifier_recipe(order, row, SimpleNamespace(name="MODIFIER-PRODUCT"), 1, "Main")
		self.assertEqual(
			[item.item for item in parse_json_rows(row.recipe_snapshot)],
			["BASE-INGREDIENT", "ADDON-INGREDIENT"],
		)
		self.assertEqual(
			[item.source_selling_product for item in parse_json_rows(row.recipe_snapshot)],
			["BASE-PRODUCT", "MODIFIER-PRODUCT"],
		)
