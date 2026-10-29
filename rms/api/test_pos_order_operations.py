import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from rms.api.pos import assert_store_access, cancel_confirmed_order_item, cancel_order, confirm_order, create_recipe_stock_entry, discount_exceeds_pos_user_limit, ensure_guest_check_allocations_unchanged, ensure_payment_rows_for_total, get_active_pos_user, get_guest_checks, get_kitchen_board, get_open_order_check_print_html, get_open_order_overview, get_owned_draft_order, get_pos_capabilities, get_pos_sales_history_filters, get_pos_user_scope_values, get_product_configuration, get_pos_invoice_print_html, get_store_open_orders, get_tables, is_pos_scope_allowed, merge_orders, pay_order, preview_order_discount, require_kitchen_capability, require_pos_action, require_pos_scope, resplit_open_guest_check, set_kitchen_ticket_status, split_order, update_order_item_notes, validate_guest_check_allocations, validate_guest_check_resplit, validate_guest_payment_rows, validate_guest_item_allocations, validate_payment_change, validate_pos_discount_value, pos_discount_approval_context_hash, verify_pos_discount_manager_password
from rms.api.pos import allocate_change_to_order_payments
from rms.rms.doctype.pos_order.pos_order import POSOrder, ensure_confirmed_guest_checks_unchanged, ensure_guest_check_item_append_only
from rms.rms.doctype.kitchen_ticket.kitchen_ticket import KitchenTicket


class TestPOSOrderOperations(unittest.TestCase):
	def test_guest_check_payable_uses_brand_rounding_and_saved_invoice_amount(self):
		open_check = SimpleNamespace(name="CHECK-OPEN", guest_name="Guest 2", status="Open", grand_total=80.49,
			discount_type="Percentage", discount_value=0, discount_amount=0, discount_scope="Net Total",
			discount_reason="", pos_invoice=None)
		paid_check = SimpleNamespace(name="CHECK-PAID", guest_name="Guest 1", status="Paid", grand_total=80.49,
			discount_type="Percentage", discount_value=0, discount_amount=0, discount_scope="Net Total",
			discount_reason="", pos_invoice="POSINV-1")
		order = SimpleNamespace(name="ORDER-1", store="STORE-1", restaurant_brand="BRAND-1", items=[],
			guest_checks=[paid_check, open_check])

		def get_value(doctype, *args, **kwargs):
			if doctype == "Restaurant Brand":
				return "Round Up"
			if doctype == "POS Invoice":
				return frappe._dict(rounded_total=81, grand_total=80.49)
			return None

		get_real_doc = frappe.get_doc
		def get_doc(doctype, *args, **kwargs):
			return order if doctype == "POS Order" else get_real_doc(doctype, *args, **kwargs)

		with patch("rms.api.pos.frappe.get_doc", side_effect=get_doc), \
				patch("rms.api.pos.assert_store_access"), patch("rms.api.pos.require_order_scope"), \
				patch("rms.api.pos.get_guest_check_item_allocations", return_value={}), \
				patch("rms.api.pos.frappe.db.get_value", side_effect=get_value):
			checks = get_guest_checks("ORDER-1")["guest_checks"]

		self.assertEqual([check["payable_total"] for check in checks], [81, 81])

	def test_open_guest_check_print_uses_brand_rounded_payable(self):
		check = SimpleNamespace(name="CHECK-1", guest_name="Guest 1", status="Open", grand_total=80.49,
			pos_invoice=None)
		order = SimpleNamespace(name="ORDER-1", store="STORE-1", status="Confirmed", cashier_session=None,
			restaurant_brand="BRAND-1", items=[], guest_checks=[check], dining_table="", check_label="",
			grand_total=80.49, modified="2026-10-27")
		get_real_doc = frappe.get_doc
		def get_doc(doctype, *args, **kwargs):
			return order if doctype == "POS Order" else get_real_doc(doctype, *args, **kwargs)

		with patch("rms.api.pos.frappe.get_doc", side_effect=get_doc), \
				patch("rms.api.pos.assert_store_access"), patch("rms.api.pos.require_order_scope"), \
				patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.get_guest_check_item_allocations", return_value={}), \
				patch("rms.api.pos.get_active_order_item_qty", return_value=0), \
				patch("rms.api.pos.frappe.get_roles", return_value=["System Manager"]), \
				patch("rms.api.pos.frappe.db.get_value", side_effect=lambda doctype, *args, **kwargs:
					"Round Up" if doctype == "Restaurant Brand" else None):
			html = get_open_order_check_print_html("ORDER-1", "CHECK-1")
		self.assertIn("81.00", html)

	def test_discount_preview_is_exposed_as_a_whitelisted_method(self):
		frappe.is_whitelisted(preview_order_discount)

	def test_product_configuration_returns_missing_regular_product_price_as_none(self):
		product = frappe._dict(name="PRODUCT-1", title="Unpriced Tea", enabled=1, has_options=0, uom="Nos",
			option_products=[], modifier_groups=[], modifier_options=[], resolve_price=lambda *args, **kwargs: None)
		with patch("rms.api.pos.require_pos_role"), patch("rms.api.pos.assert_store_access"), \
				patch("rms.api.pos.get_brands", return_value=[{"name": "BRAND-1"}]), \
				patch("rms.api.pos.get_order_types", return_value=[{"name": "Dine In"}]), \
				patch("rms.api.pos.frappe.get_doc", return_value=product), \
				patch("rms.api.pos.frappe.get_cached_value", return_value=1):
			configuration = get_product_configuration("PRODUCT-1", "STORE-1", "BRAND-1", "Dine In")
		self.assertIsNone(configuration["price"])
		self.assertEqual(configuration["options"], [])

	def test_product_configuration_marks_an_unpriced_child_option_without_a_price(self):
		child = frappe._dict(name="OPTION-1", title="Unpriced Tea - Small", enabled=1, has_options=0, uom="Nos",
			option_products=[], modifier_groups=[], modifier_options=[], resolve_price=lambda *args, **kwargs: None)
		parent = frappe._dict(name="PRODUCT-1", title="Unpriced Tea", enabled=1, has_options=1, uom="Nos",
			option_products=[frappe._dict(option_product="OPTION-1", sequence_id=1)],
			modifier_groups=[], modifier_options=[])
		with patch("rms.api.pos.require_pos_role"), patch("rms.api.pos.assert_store_access"), \
				patch("rms.api.pos.get_brands", return_value=[{"name": "BRAND-1"}]), \
				patch("rms.api.pos.get_order_types", return_value=[{"name": "Dine In"}]), \
				patch("rms.api.pos.frappe.get_doc", side_effect=[parent, child]), \
				patch("rms.api.pos.frappe.db.get_value", return_value=frappe._dict(title=child.title, enabled=1, has_options=0)), \
				patch("rms.api.pos.frappe.get_cached_value", return_value=1):
			configuration = get_product_configuration("PRODUCT-1", "STORE-1", "BRAND-1", "Dine In")
		self.assertTrue(configuration["has_options"])
		self.assertIsNone(configuration["options"][0]["price"])
		self.assertIsNone(configuration["options"][0]["price_list"])

	def test_split_payment_trims_guest_names_and_aggregates_same_tender(self):
		rows, totals = validate_guest_payment_rows([
			{"guest": " Mariam ", "mode_of_payment": "Cash", "amount": 4.25},
			{"guest": "Omar", "mode_of_payment": "Cash", "amount": 5.75},
		], {"Cash"})
		self.assertEqual(rows, [
			{"guest": "Mariam", "mode_of_payment": "Cash", "amount": 4.25, "due_amount": 4.25, "items": [], "split_mode": "amount"},
			{"guest": "Omar", "mode_of_payment": "Cash", "amount": 5.75, "due_amount": 5.75, "items": [], "split_mode": "amount"},
		])
		self.assertEqual(totals, {"Cash": 10.0})

	def test_split_payment_accepts_more_than_two_guests(self):
		rows, totals = validate_guest_payment_rows([
			{"guest": name, "mode_of_payment": "Cash", "amount": 1}
			for name in ("Mariam", "Omar", "Salma")
		], {"Cash"})
		self.assertEqual(len(rows), 3)
		self.assertEqual(totals, {"Cash": 3.0})

	def test_cash_tender_over_total_returns_change(self):
		paid, change = validate_payment_change([
			{"mode_of_payment": "Cash", "amount": 200},
		], 155)
		self.assertEqual((paid, change), (200, 45))

	def test_non_cash_overpayment_returns_change(self):
		paid, change = validate_payment_change([
			{"mode_of_payment": "Card", "amount": 150},
			{"mode_of_payment": "Mobile Wallet", "amount": 120},
		], 106.02)
		self.assertEqual(paid, 270)
		self.assertAlmostEqual(change, 163.98)

	def test_order_payment_rows_net_card_overpayment_to_invoice_total(self):
		rows = allocate_change_to_order_payments([{"mode_of_payment": "Credit Card", "amount": 40}], 11.5)
		self.assertEqual(rows, [{"mode_of_payment": "Credit Card", "amount": 28.5}])

	def test_order_payment_rows_use_cash_first_then_card_for_change(self):
		rows = allocate_change_to_order_payments([
			{"mode_of_payment": "Cash", "amount": 5}, {"mode_of_payment": "Credit Card", "amount": 40}], 11.5, {"Cash"})
		self.assertEqual(rows, [{"mode_of_payment": "Credit Card", "amount": 33.5}])

	def test_fully_discounted_order_can_close_without_payment_method(self):
		self.assertEqual(ensure_payment_rows_for_total([], ["Cash", "Card"], 0), [
			{"mode_of_payment": "Cash", "amount": 0},
		])
		with self.assertRaisesRegex(frappe.ValidationError, "Set at least one Mode of Payment"):
			ensure_payment_rows_for_total([], [], 0)
		with self.assertRaisesRegex(frappe.ValidationError, "Select at least one Mode of Payment"):
			ensure_payment_rows_for_total([], ["Cash"], 100)

	def test_fully_discounted_split_checks_allow_zero_amounts(self):
		rows, totals = validate_guest_payment_rows([
			{"guest": "Mariam", "mode_of_payment": "Cash", "amount": 0},
			{"guest": "Omar", "mode_of_payment": "Cash", "amount": 0},
		], {"Cash"}, allow_zero=True)
		self.assertEqual(len(rows), 2)
		self.assertEqual(totals, {"Cash": 0})

	def test_discount_approval_fingerprint_is_bound_to_order_and_terms(self):
		args = ("ORDER-1", "cashier@example.com", "STORE-1", "Percentage", 20, "Service recovery", "Net Total")
		fingerprint = pos_discount_approval_context_hash(*args)
		self.assertEqual(fingerprint, pos_discount_approval_context_hash(*args))
		self.assertNotEqual(fingerprint, pos_discount_approval_context_hash("ORDER-2", *args[1:]))
		self.assertNotEqual(fingerprint, pos_discount_approval_context_hash(*args[:4], 21, *args[5:]))

	def test_fixed_discount_cannot_exceed_invoice_total(self):
		with self.assertRaisesRegex(frappe.ValidationError, "cannot exceed the invoice total"):
			validate_pos_discount_value("Amount", 100.01, 100)
		self.assertEqual(validate_pos_discount_value("Amount", 100, 100), 100)

	def test_percentage_discount_is_limited_to_one_hundred(self):
		with self.assertRaisesRegex(frappe.ValidationError, "cannot exceed 100%"):
			validate_pos_discount_value("Percentage", 100.01, 100)
		self.assertEqual(validate_pos_discount_value("Percentage", 100, 100), 100)

	def test_cashier_discount_approval_uses_the_configured_percentage_limit(self):
		pos_user = frappe._dict(can_apply_manual_discount=1, max_manual_discount_percent=10)
		with patch("rms.api.pos.frappe.get_roles", return_value=["POS Cashier"]), \
				patch("rms.api.pos.frappe.db.get_value", return_value=pos_user):
			self.assertFalse(discount_exceeds_pos_user_limit("cashier@example.com", "Percentage", 5, "Net Total", 100, 110))
			self.assertTrue(discount_exceeds_pos_user_limit("cashier@example.com", "Percentage", 15, "Net Total", 100, 110))

	def test_explicit_pos_user_discount_limit_also_applies_to_system_manager_cashier(self):
		pos_user = frappe._dict(can_apply_manual_discount=1, max_manual_discount_percent=50)
		with patch("rms.api.pos.frappe.get_roles", return_value=["System Manager"]), \
				patch("rms.api.pos.frappe.db.get_value", return_value=pos_user):
			self.assertFalse(discount_exceeds_pos_user_limit("Administrator", "Percentage", 50, "Net Total", 100, 110))
			self.assertTrue(discount_exceeds_pos_user_limit("Administrator", "Percentage", 55, "Net Total", 100, 110))

	def test_over_limit_discount_preview_returns_manager_choices_without_throwing(self):
		order = frappe._dict(name="ORDER-1", store="STORE-1", cashier_session="SESSION-1", subtotal=100,
			flags=frappe._dict(), validate_discount=unittest.mock.Mock(),
			calculate_tax_preview=unittest.mock.Mock(side_effect=[(0, 100), (0, 80)]))
		with patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.assert_store_access"), \
				patch("rms.api.pos.require_order_scope"), \
				patch("rms.api.pos.frappe.get_doc", side_effect=[order, frappe._dict(manual_discount_scope="Net Total")]), \
				patch("rms.api.pos.frappe.db.get_value", return_value="SESSION-1"), \
				patch("rms.api.pos.frappe.session", frappe._dict(user="cashier@example.com")), \
				patch("rms.api.pos.discount_exceeds_pos_user_limit", return_value=True), \
				patch("rms.api.pos.get_pos_discount_approvers", return_value=[{"user": "manager@example.com", "full_name": "POS Manager"}]), \
				patch("rms.rms.doctype.pos_order.pos_order.calculate_discount_amount", return_value=20) as calculate_discount:
			result = preview_order_discount("ORDER-1", "Percentage", 20, "Service recovery")
		self.assertTrue(result["requires_manager_approval"])
		self.assertEqual(result["approvers"][0]["user"], "manager@example.com")
		self.assertEqual(result["grand_total"], 80)
		self.assertEqual(result["discount_amount"], 20)
		self.assertEqual(calculate_discount.call_args.args, (100, 0, "Percentage", 20.0, "Net Total", 100))
		order.validate_discount.assert_called_once_with(100, 0, 100)

	def test_discount_preview_cannot_change_discount_after_a_guest_check_is_paid(self):
		order = frappe._dict(name="ORDER-1", store="STORE-1", cashier_session="SESSION-1", subtotal=100,
			discount_type="Percentage", discount_value=10, discount_reason="Existing discount",
			guest_checks=[frappe._dict(status="Paid")], flags=frappe._dict())
		with patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.assert_store_access"), \
				patch("rms.api.pos.require_order_scope"), \
				patch("rms.api.pos.frappe.get_doc", side_effect=[order, frappe._dict(manual_discount_scope="Net Total")]), \
				patch("rms.api.pos.frappe.db.get_value", return_value="SESSION-1"), \
				patch("rms.api.pos.frappe.session", frappe._dict(user="cashier@example.com")):
			with self.assertRaisesRegex(frappe.ValidationError, "Use an open guest check to apply a discount"):
				preview_order_discount("ORDER-1", "Percentage", 20, "Changed discount")

	def test_open_guest_check_discount_preview_is_scoped_after_another_check_is_paid(self):
		paid = frappe._dict(name="PAID", status="Paid", grand_total=40, discount_amount=0)
		opened = frappe._dict(name="OPEN", status="Open", grand_total=60, discount_amount=0)
		order = frappe._dict(name="ORDER-1", store="STORE-1", cashier_session="SESSION-1", discount_amount=0,
			discount_scope="Net Total", guest_checks=[paid, opened])
		store = frappe._dict(manual_discount_scope="Net Total")
		preview = {"discount_amount": 5, "grand_total": 55, "subtotal": 60, "baseline_grand_total": 60,
			"discount_value": 10, "discount_type": "Percentage", "discount_scope": "Net Total",
			"discount_reason": "Tea", "requires_manager_approval": False, "approved_by": None, "approval_token": None}
		with patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.assert_store_access"), \
				patch("rms.api.pos.require_order_scope"), patch("rms.api.pos.frappe.get_doc", side_effect=[order, store]), \
				patch("rms.api.pos.frappe.db.get_value", return_value="SESSION-1"), \
				patch("rms.api.pos.frappe.session", frappe._dict(user="cashier@example.com")), \
				patch("rms.api.pos.get_guest_check_discount_totals", return_value=preview) as totals, \
				patch("rms.api.pos.discount_exceeds_pos_user_limit", return_value=False):
			result = preview_order_discount("ORDER-1", "Percentage", 10, "Tea", guest_check_name="OPEN")
		self.assertEqual(result["discount_amount"], 5)
		self.assertEqual(result["grand_total"], 55)
		self.assertEqual(paid.grand_total, 40, "the paid guest check remains untouched")
		self.assertEqual(totals.call_args.args[:2], (order, opened))
	def test_manager_password_mints_context_bound_one_time_approval_token(self):
		challenge = frappe._dict(flags=frappe._dict(), insert=unittest.mock.Mock())
		manager_user = frappe._dict(get_password=unittest.mock.Mock(return_value="manager-password"))
		with patch("rms.api.pos.get_pos_discount_approvers", return_value=[{"user": "manager@example.com"}]), \
				patch("rms.api.pos._get_discount_password_failure_count", return_value=0), \
				patch("rms.api.pos._clear_discount_password_failures") as clear_failures, \
				patch("rms.api.pos.frappe.new_doc", return_value=challenge), \
				patch("rms.api.pos.frappe.db.get_value", return_value="POS-USER-MANAGER"), \
				patch("rms.api.pos.frappe.get_doc", return_value=manager_user), \
				patch("rms.api.pos.frappe.session", frappe._dict(user="cashier@example.com")), \
				patch("frappe.utils.now_datetime", return_value="2026-01-01 00:00:00"), \
				patch("frappe.utils.add_to_date", return_value="2026-01-01 00:05:00"), \
				patch("rms.api.pos._record_discount_password_failure") as record_failure:
			result = verify_pos_discount_manager_password(frappe._dict(name="ORDER-1", store="STORE-1", discount_scope="Net Total"),
				"manager@example.com", "manager-password", "Percentage", 60, "Service recovery")
		manager_user.get_password.assert_called_once_with("discount_approval_password", raise_exception=False)
		record_failure.assert_not_called()
		self.assertEqual(result["approver"], "manager@example.com")
		self.assertTrue(result["approval_token"])
		self.assertNotEqual(result["approval_token"], "manager-password")
		clear_failures.assert_called_once()
		self.assertEqual(challenge.approval_context_hash, pos_discount_approval_context_hash(
			"ORDER-1", "cashier@example.com", "STORE-1", "Percentage", 60, "Service recovery", "Net Total"))
		challenge.insert.assert_called_once_with(ignore_permissions=True)

	def test_manager_password_verification_locks_after_five_bad_attempts(self):
		with patch("rms.api.pos.get_pos_discount_approvers", return_value=[{"user": "manager@example.com"}]), \
				patch("rms.api.pos._get_discount_password_failure_count", return_value=5), \
				patch("rms.api.pos.frappe.session", frappe._dict(user="cashier@example.com")), \
				patch("rms.api.pos.frappe.db.get_value") as get_value:
			with self.assertRaisesRegex(frappe.ValidationError, "locked for five minutes"):
				verify_pos_discount_manager_password(frappe._dict(name="ORDER-1", store="STORE-1"),
					"manager@example.com", "wrong", "Percentage", 60, "Service recovery")
		get_value.assert_not_called()

	def test_incorrect_manager_fixed_password_records_a_limited_attempt(self):
		manager_user = frappe._dict(get_password=unittest.mock.Mock(return_value="correct-secret"))
		with patch("rms.api.pos.get_pos_discount_approvers", return_value=[{"user": "manager@example.com"}]), \
				patch("rms.api.pos._get_discount_password_failure_count", return_value=2), \
				patch("rms.api.pos._record_discount_password_failure") as record_failure, \
				patch("rms.api.pos.frappe.db.get_value", return_value="POS-USER-MANAGER"), \
				patch("rms.api.pos.frappe.get_doc", return_value=manager_user), \
				patch("rms.api.pos.frappe.session", frappe._dict(user="cashier@example.com")):
			with self.assertRaisesRegex(frappe.ValidationError, "manager approval password is incorrect"):
				verify_pos_discount_manager_password(frappe._dict(name="ORDER-1", store="STORE-1"),
					"manager@example.com", "wrong-secret", "Percentage", 60, "Service recovery")
		record_failure.assert_called_once()

	def test_missing_manager_password_uses_same_incorrect_password_response(self):
		with patch("rms.api.pos.get_pos_discount_approvers", return_value=[{"user": "manager@example.com"}]), \
				patch("rms.api.pos._get_discount_password_failure_count", return_value=0), \
				patch("rms.api.pos._record_discount_password_failure") as record_failure, \
				patch("rms.api.pos.frappe.db.get_value", return_value=None), \
				patch("rms.api.pos.frappe.session", frappe._dict(user="cashier@example.com")):
			with self.assertRaisesRegex(frappe.ValidationError, "manager approval password is incorrect"):
				verify_pos_discount_manager_password(frappe._dict(name="ORDER-1", store="STORE-1"),
					"manager@example.com", "wrong-secret", "Percentage", 60, "Service recovery")
		record_failure.assert_called_once()

	def test_item_split_requires_every_active_item_exactly_once(self):
		guest_rows = [
			{"split_mode": "items", "due_amount": 60, "items": ["ORDER-ITEM-1"]},
			{"split_mode": "items", "due_amount": 40, "items": ["ORDER-ITEM-2"]},
		]
		validate_guest_item_allocations(guest_rows, ["ORDER-ITEM-1", "ORDER-ITEM-2"], 100)
		with self.assertRaisesRegex(frappe.ValidationError, "Assign 100% of every active order item"):
			validate_guest_item_allocations(guest_rows, ["ORDER-ITEM-1", "ORDER-ITEM-2", "ORDER-ITEM-3"], 100)

	def test_single_item_can_be_split_between_people_by_percentage(self):
		guest_rows = [
			{"split_mode": "items", "due_amount": 25, "items": [{"item_name": "ORDER-ITEM-1", "share": 0.25}]},
			{"split_mode": "items", "due_amount": 75, "items": [{"item_name": "ORDER-ITEM-1", "share": 0.75}]},
		]
		validate_guest_item_allocations(guest_rows, ["ORDER-ITEM-1"], 100, {"ORDER-ITEM-1": 100})

	def test_item_split_requires_all_shares_to_total_one_hundred_percent(self):
		guest_rows = [
			{"split_mode": "items", "due_amount": 50, "items": [{"item_name": "ORDER-ITEM-1", "share": 0.5}]},
			{"split_mode": "items", "due_amount": 50, "items": [{"item_name": "ORDER-ITEM-1", "share": 0.25}]},
		]
		with self.assertRaisesRegex(frappe.ValidationError, "Assign 100% of every active order item"):
			validate_guest_item_allocations(guest_rows, ["ORDER-ITEM-1"], 100, {"ORDER-ITEM-1": 100})

	def test_guest_checks_assign_each_complete_order_line_to_one_guest(self):
		order_items = [frappe._dict(name="LINE-LEMON", qty=1, cancelled_qty=0),
			frappe._dict(name="LINE-TEA", qty=1, cancelled_qty=0)]
		checks = [
			{"guest_name": "Guest 1", "items": ["LINE-LEMON"]},
			{"guest_name": "Guest 2", "items": ["LINE-TEA"]},
		]
		result = validate_guest_check_allocations(order_items, checks)
		self.assertEqual([row["guest_name"] for row in result], ["Guest 1", "Guest 2"])
		self.assertEqual([row["items"] for row in result], [[{"name": "LINE-LEMON", "qty": 1}], [{"name": "LINE-TEA", "qty": 1}]])

	def test_guest_checks_reject_duplicate_or_unassigned_order_lines(self):
		order_items = [frappe._dict(name="LINE-LEMON", qty=1, cancelled_qty=0),
			frappe._dict(name="LINE-TEA", qty=1, cancelled_qty=0)]
		with self.assertRaisesRegex(frappe.ValidationError, "Assign every active order item exactly once"):
			validate_guest_check_allocations(order_items, [
				{"guest_name": "Guest 1", "items": ["LINE-LEMON", "LINE-TEA"]},
				{"guest_name": "Guest 2", "items": ["LINE-LEMON"]},
			])
		result = validate_guest_check_allocations(order_items, [
			{"guest_name": "Guest 1", "items": ["LINE-LEMON", "LINE-TEA"]},
			{"guest_name": "Guest 2", "items": []},
		])
		self.assertEqual(result[1]["items"], [], "new guest can start with no quantity assigned")

	def test_guest_checks_can_split_quantities_from_one_order_line(self):
		order_items = [frappe._dict(name="LINE-LEMON", qty=7, cancelled_qty=0),
			frappe._dict(name="LINE-TEA", qty=2, cancelled_qty=0)]
		result = validate_guest_check_allocations(order_items, [
			{"guest_name": "Guest 1", "items": [{"name": "LINE-LEMON", "qty": 5}, {"name": "LINE-TEA", "qty": 2}]},
			{"guest_name": "Guest 2", "items": [{"name": "LINE-LEMON", "qty": 2}]},
		])
		self.assertEqual(result[0]["items"][0]["qty"], 5)
		self.assertEqual(result[1]["items"][0]["qty"], 2)

	def test_guest_checks_reject_fractional_quantity_for_whole_number_items(self):
		order_items = [frappe._dict(name="LINE-LEMON", qty=3, cancelled_qty=0, must_be_whole_number=True),
			frappe._dict(name="LINE-TEA", qty=1, cancelled_qty=0)]
		with self.assertRaisesRegex(frappe.ValidationError, "Whole-number items cannot be split into fractional quantities"):
			validate_guest_check_allocations(order_items, [
				{"guest_name": "Guest 1", "items": [{"name": "LINE-LEMON", "qty": 2.5}, "LINE-TEA"]},
				{"guest_name": "Guest 2", "items": [{"name": "LINE-LEMON", "qty": 0.5}]},
			])

	def test_confirmed_guest_checks_cannot_be_changed_when_order_is_saved(self):
		item = frappe._dict(name="LINE-1", selling_product="TEA", option_parent=None, item="TEA", qty=2,
			cancelled_qty=0, uom="Nos", selling_price=10, price_list="Standard", amount=20, warehouse="WH",
			preparation_area="KITCHEN", notes=None, modifiers="[]", recipe_snapshot="[]")
		check = frappe._dict(guest_name="Guest 1", status="Open", items_json='[{"name":"LINE-1","qty":2}]')
		previous = SimpleNamespace(items=[item], guest_checks=[check])
		current = SimpleNamespace(items=[frappe._dict(item)], guest_checks=[frappe._dict(check, status="Paid", pos_invoice="INV-1")])
		ensure_confirmed_guest_checks_unchanged(previous, current)
		current.guest_checks[0].guest_name = "Guest 2"
		with self.assertRaisesRegex(frappe.ValidationError, "Guest checks are confirmed and cannot be changed"):
			ensure_confirmed_guest_checks_unchanged(previous, current)
		current.guest_checks[0].guest_name = "Guest 1"
		current.items[0].qty = 1
		with self.assertRaisesRegex(frappe.ValidationError, "Order items cannot be changed after guest checks are confirmed"):
			ensure_confirmed_guest_checks_unchanged(previous, current)

	def test_confirmed_guest_checks_cannot_be_reassigned(self):
		items = [frappe._dict(name="LINE-LEMON", qty=2, cancelled_qty=0),
			frappe._dict(name="LINE-TEA", qty=1, cancelled_qty=0)]
		order = SimpleNamespace(items=items, guest_checks=[
			frappe._dict(guest_name="Guest 1", status="Open", items_json='[{"name":"LINE-LEMON","qty":2}]'),
			frappe._dict(guest_name="Guest 2", status="Open", items_json='[{"name":"LINE-TEA","qty":1}]'),
		])
		assert ensure_guest_check_allocations_unchanged(order, [
			{"guest_name": "Guest 1", "items": [{"name": "LINE-LEMON", "qty": 2}]},
			{"guest_name": "Guest 2", "items": [{"name": "LINE-TEA", "qty": 1}]},
		]) is True
		with self.assertRaisesRegex(frappe.ValidationError, "Guest checks are already confirmed and cannot be changed"):
			ensure_guest_check_allocations_unchanged(order, [
				{"guest_name": "Guest 1", "items": [{"name": "LINE-LEMON", "qty": 1}, {"name": "LINE-TEA", "qty": 1}]},
				{"guest_name": "Guest 2", "items": [{"name": "LINE-LEMON", "qty": 1}]},
			])

	def test_open_guest_check_can_be_resplit_without_changing_paid_or_other_open_checks(self):
		items = [frappe._dict(name="TEA", qty=1, cancelled_qty=0), frappe._dict(name="LEMON", qty=1, cancelled_qty=0), frappe._dict(name="MEAL", qty=1, cancelled_qty=0)]
		checks = [
			frappe._dict(name="PAID-CHECK", guest_name="Guest 1", status="Paid", items_json='[{"name":"TEA","qty":1}]'),
			frappe._dict(name="TARGET-CHECK", guest_name="Guest 2", status="Open", items_json='[{"name":"LEMON","qty":1},{"name":"MEAL","qty":1}]'),
			frappe._dict(name="OTHER-CHECK", guest_name="Guest 3", status="Open", items_json='[]'),
		]
		result = validate_guest_check_resplit(items, checks, "TARGET-CHECK", [
			{"guest_name": "Guest 2", "items": ["LEMON"]},
			{"guest_name": "Guest 4", "items": ["MEAL"]},
		])
		self.assertEqual([row["guest_name"] for row in result], ["Guest 1", "Guest 2", "Guest 4", "Guest 3"])
		self.assertEqual(result[0]["items"], [{"name": "TEA", "qty": 1}])
		self.assertEqual(result[1]["items"], [{"name": "LEMON", "qty": 1}])
		self.assertEqual(result[2]["items"], [{"name": "MEAL", "qty": 1}])
		self.assertEqual(result[3]["items"], [])

	def test_open_guest_check_resplit_accepts_pos_order_item_documents(self):
		items = [
			frappe.get_doc({"doctype": "POS Order Item", "name": "TEA", "qty": 2, "cancelled_qty": 0}),
			frappe.get_doc({"doctype": "POS Order Item", "name": "LEMON", "qty": 1, "cancelled_qty": 0}),
		]
		checks = [
			frappe._dict(name="TARGET-CHECK", guest_name="Guest 1", status="Open",
				items_json='[{"name":"TEA","qty":2},{"name":"LEMON","qty":1}]'),
			frappe._dict(name="OTHER-CHECK", guest_name="Guest 2", status="Open", items_json="[]"),
		]
		result = validate_guest_check_resplit(items, checks, "TARGET-CHECK", [
			{"guest_name": "Guest 1", "items": [{"name": "TEA", "qty": 1}, {"name": "LEMON", "qty": 1}]},
			{"guest_name": "Guest 3", "items": [{"name": "TEA", "qty": 1}]},
		])
		self.assertEqual([row["guest_name"] for row in result], ["Guest 1", "Guest 3", "Guest 2"])
		self.assertEqual(result[0]["items"], [{"name": "TEA", "qty": 1.0}, {"name": "LEMON", "qty": 1.0}])
		self.assertEqual(result[1]["items"], [{"name": "TEA", "qty": 1.0}])
		self.assertEqual(result[2]["items"], [])

	def test_paid_guest_check_cannot_be_resplit(self):
		items = [frappe._dict(name="TEA", qty=1, cancelled_qty=0), frappe._dict(name="LEMON", qty=1, cancelled_qty=0)]
		checks = [frappe._dict(name="PAID-CHECK", guest_name="Guest 1", status="Paid", items_json='[{"name":"TEA","qty":1},{"name":"LEMON","qty":1}]')]
		with self.assertRaisesRegex(frappe.ValidationError, "Only an open guest check can be split again"):
			validate_guest_check_resplit(items, checks, "PAID-CHECK", [
				{"guest_name": "Guest 1", "items": ["TEA"]}, {"guest_name": "Guest 2", "items": ["LEMON"]},
			])

	def test_resplitting_persists_only_the_selected_open_check(self):
		def item(name, price):
			return frappe._dict(name=name, qty=1, cancelled_qty=0, selling_price=price, modifiers="[]")
		paid = frappe._dict(name="PAID-CHECK", guest_name="Guest 1", status="Paid", grand_total=25,
			items_json='[{"name":"PAID-LINE","qty":1}]', pos_invoice="INV-1", payments_json='[]')
		target = frappe._dict(name="TARGET-CHECK", guest_name="Guest 2", status="Open", grand_total=70,
			items_json='[{"name":"LEMON","qty":1},{"name":"TEA","qty":1}]', pos_invoice=None, payments_json='[]')
		other = frappe._dict(name="OTHER-CHECK", guest_name="Guest 3", status="Open", grand_total=35,
			items_json='[{"name":"MEAL","qty":1}]', pos_invoice=None, payments_json='[]')
		checks = [paid, target, other]
		order = SimpleNamespace(name="ORDER-1", store="STORE-1", cashier_session=None, status="Confirmed", pos_invoice=None,
			items=[item("PAID-LINE", 25), item("LEMON", 50), item("TEA", 20), item("MEAL", 35)], guest_checks=checks, discount_amount=0, discount_scope="Net Total",
			flags=frappe._dict())
		order.append = lambda field, values: checks.append(frappe._dict(name="NEW-CHECK", **values))
		order.save = lambda **kwargs: None
		with patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.assert_store_access"), \
				patch("rms.api.pos.require_order_scope"), patch("rms.api.pos.frappe.get_doc", return_value=order), \
				patch("rms.api.pos.get_guest_checks", return_value={"guest_checks": []}), \
				patch("rms.api.pos.get_guest_check_discount_totals", side_effect=lambda current_order, check: {"discount_amount": 0, "grand_total": check.grand_total, "final_tax_total": 0}):
			resplit_open_guest_check("ORDER-1", "TARGET-CHECK", [
				{"guest_name": "Guest 2", "items": ["LEMON"]},
				{"guest_name": "Guest 4", "items": ["TEA"]},
			])
		self.assertEqual((paid.status, paid.grand_total, paid.pos_invoice, paid.items_json),
			("Paid", 25, "INV-1", '[{"name":"PAID-LINE","qty":1}]'))
		self.assertEqual((other.status, other.grand_total, other.items_json),
			("Open", 35, '[{"name":"MEAL","qty":1}]'))
		self.assertEqual((target.guest_name, target.grand_total, target.items_json),
			("Guest 2", 50, '[{"name": "LEMON", "qty": 1.0}]'))
		self.assertEqual(checks[-1].guest_name, "Guest 4")
		self.assertEqual(checks[-1].grand_total, 20)

	def test_appended_order_items_must_be_assigned_to_first_open_check(self):
		def item(name):
			return frappe._dict(name=name, selling_product="TEA", option_parent=None, item="TEA", qty=1,
				cancelled_qty=0, uom="Nos", selling_price=10, price_list="Standard", amount=10, warehouse="WH",
				preparation_area="KITCHEN", notes=None, modifiers="[]", recipe_snapshot="[]")
		old_checks = [
			frappe._dict(name="PAID", guest_name="Guest 1", status="Paid", pos_invoice="INV-1", grand_total=10,
				items_json='[{"name":"LINE-1","qty":1}]'),
			frappe._dict(name="OPEN", guest_name="Guest 2", status="Open", pos_invoice=None, grand_total=10,
				items_json='[{"name":"LINE-2","qty":1}]'),
		]
		previous = SimpleNamespace(items=[item("LINE-1"), item("LINE-2")], guest_checks=old_checks)
		current_checks = [frappe._dict(old_checks[0]), frappe._dict(old_checks[1], grand_total=20,
			items_json='[{"name":"LINE-2","qty":1},{"name":"LINE-3","qty":1}]')]
		current = SimpleNamespace(items=[item("LINE-1"), item("LINE-2"), item("LINE-3")], guest_checks=current_checks)
		ensure_guest_check_item_append_only(previous, current)
		current_checks[1].items_json = '[{"name":"LINE-2","qty":1}]'
		with self.assertRaisesRegex(frappe.ValidationError, "New items must be assigned to the first open guest check"):
			ensure_guest_check_item_append_only(previous, current)

	def test_save_order_gives_appended_items_stable_names_before_guest_check_assignment(self):
		from rms.api.pos import save_order

		new_child = frappe.new_doc("POS Order").append("items", {"name": "LINE-NEW", "__islocal": 1})
		self.assertTrue(new_child.is_new(), "a generated child name must still be inserted as a new row")
		open_check = frappe._dict(name="CHECK-OPEN", guest_name="Guest 2", status="Open", pos_invoice=None,
			grand_total=10, items_json='[{"name":"LINE-OLD","qty":1}]')
		order = frappe._dict(name="ORDER-1", store="STORE-1", cashier_session="SESSION-1", status="Confirmed",
			restaurant_brand="BRAND-1", order_type="Takeaway", subtotal=20, tax_total=0, grand_total=20,
			sales_taxes_and_charges_template=None, items=[frappe._dict(name="LINE-OLD", qty=1)], guest_checks=[open_check],
			flags=frappe._dict())
		def append_item(fieldname, values):
			self.assertEqual(fieldname, "items")
			row = frappe._dict(values)
			order["items"].append(row)
			return row
		order.append = append_item
		order.is_new = lambda: False
		order.save = lambda **kwargs: None
		store = frappe._dict(name="STORE-1")
		session = frappe._dict(name="SESSION-1", status="Open", user=frappe.session.user)
		with patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.assert_store_access", return_value=store), \
				patch("rms.api.pos.get_user_session", return_value=session), patch("rms.api.pos.require_order_scope"), \
				patch("rms.api.pos.get_brands", return_value=[{"name": "BRAND-1"}]), \
				patch("rms.api.pos.get_order_types", return_value=[{"name": "Takeaway"}]), \
				patch("rms.api.pos.frappe.get_doc", return_value=order), \
				patch("rms.api.pos.frappe.generate_hash", return_value="LINE-NEW"), \
				patch("rms.api.pos.get_guest_checks", return_value={"guest_checks": []}):
			result = save_order(json.dumps({"name": "ORDER-1", "store": "STORE-1", "restaurant_brand": "BRAND-1",
				"order_type": "Takeaway", "items": [{"selling_product": "TEA", "qty": 1}]}))
		self.assertEqual(result["appended_items"], [{"client_key": "", "name": "LINE-NEW"}])
		self.assertEqual(order["items"][-1]["__islocal"], 1)
		self.assertIn('"name": "LINE-NEW"', open_check.items_json)

	def test_guest_checks_reject_cancelled_and_single_line_item_splits(self):
		with self.assertRaisesRegex(frappe.ValidationError, "at least two active order items"):
			validate_guest_check_allocations([frappe._dict(name="LINE-TEA", qty=1, cancelled_qty=0)], [
				{"guest_name": "Guest 1", "items": ["LINE-TEA"]},
				{"guest_name": "Guest 2", "items": []},
			])
		order_items = [frappe._dict(name="LINE-LEMON", qty=1, cancelled_qty=0),
			frappe._dict(name="LINE-TEA", qty=1, cancelled_qty=0),
			frappe._dict(name="LINE-CANCELLED", qty=1, cancelled_qty=1)]
		with self.assertRaisesRegex(frappe.ValidationError, "Assign valid active order items"):
			validate_guest_check_allocations(order_items, [
				{"guest_name": "Guest 1", "items": ["LINE-LEMON", "LINE-CANCELLED"]},
				{"guest_name": "Guest 2", "items": ["LINE-TEA"]},
			])

	def _call_pay_order_with_guest_rows(self, guest_rows):
		order = frappe._dict(
			name="ORDER-1", store="STORE-1", cashier_session="SESSION-1", status="Confirmed", pos_invoice=None,
			customer="CUSTOMER-1", order_type="TAKEAWAY", grand_total=10,
		)
		def get_doc(doctype, name=None, *args, **kwargs):
			if isinstance(doctype, dict):
				doctype = doctype.get("doctype")
			if doctype == "POS Order":
				return order
			if doctype == "Cashier Session":
				return frappe._dict(pos_profile="PROFILE-1")
			if doctype == "POS Profile":
				return frappe._dict(customer="CUSTOMER-1", company="COMPANY-1", selling_price_list="PRICE-LIST-1")
			self.fail(f"Unexpected document lookup: {doctype} {name}")
		def get_value(doctype, *args, **kwargs):
			if doctype == "Cashier Session":
				return "cashier@example.com"
			if doctype == "Order Type Account Mapping":
				return frappe._dict(income_account="INCOME-1", cost_of_goods_sold_account="COGS-1")
			return None
		with patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.assert_store_access"), \
				patch("rms.api.pos.require_order_scope"), patch("rms.api.pos.session_payment_rows", return_value=[frappe._dict(mode_of_payment="Cash")]), \
				patch("rms.api.pos.frappe.get_doc", side_effect=get_doc), patch("rms.api.pos.frappe.db.get_value", side_effect=get_value), \
				patch("rms.api.pos.frappe.new_doc", side_effect=AssertionError("guest validation was skipped")), \
				patch("rms.api.pos.frappe.session", frappe._dict(user="cashier@example.com")):
			return pay_order("ORDER-1", '[{"mode_of_payment":"Cash","amount":10}]', guest_breakdown=frappe.as_json(guest_rows))

	def test_split_payment_rejects_duplicate_guest_names_case_insensitively(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Guest names must be different"):
			self._call_pay_order_with_guest_rows([
				{"guest": "Mariam", "mode_of_payment": "Cash", "amount": 5},
				{"guest": "  mariam ", "mode_of_payment": "Cash", "amount": 5},
			])

	def test_legacy_percentage_item_split_cannot_pay_the_whole_order(self):
		with self.assertRaisesRegex(frappe.ValidationError, "paid one guest check at a time"):
			self._call_pay_order_with_guest_rows([
				{"guest": "Mariam", "mode_of_payment": "Cash", "amount": 5, "split_mode": "items",
				 "items": [{"item_name": "LINE-1", "share": 0.5}]},
				{"guest": "Omar", "mode_of_payment": "Cash", "amount": 5, "split_mode": "items",
				 "items": [{"item_name": "LINE-1", "share": 0.5}]},
			])

	def test_unbalanced_payment_does_not_save_discount_to_the_order(self):
		order = frappe._dict(name="ORDER-1", store="STORE-1", cashier_session="SESSION-1", status="Confirmed",
			pos_invoice=None, customer="CUSTOMER-1", subtotal=100, grand_total=10, discount_value=0,
			flags=frappe._dict(), save=unittest.mock.Mock(), validate_discount=unittest.mock.Mock(),
			calculate_tax_preview=unittest.mock.Mock(side_effect=[(0, 10), (0, 9)]))
		order.save.side_effect = lambda **kwargs: setattr(order, "grand_total", 9)
		with patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.assert_store_access"), \
				patch("rms.api.pos.require_order_scope"), patch("rms.api.pos.frappe.get_doc", side_effect=[order, frappe._dict(manual_discount_scope="Net Total")]), \
				patch("rms.api.pos.frappe.db.get_value", return_value="cashier@example.com"), \
				patch("rms.api.pos.discount_exceeds_pos_user_limit", return_value=False), \
				patch("rms.api.pos.session_payment_rows", return_value=[frappe._dict(mode_of_payment="Cash")]), \
				patch("rms.api.pos.frappe.session", frappe._dict(user="cashier@example.com")):
			with self.assertRaisesRegex(frappe.ValidationError, "Payment amounts must cover"):
				pay_order("ORDER-1", '[{"mode_of_payment":"Cash","amount":8}]',
					discount_type="Amount", discount_value=1, discount_reason="Service recovery")
		order.save.assert_not_called()

	def test_payment_uses_the_active_sessions_stale_opening_entry_validator(self):
		order = SimpleNamespace(name="ORDER-1", store="STORE-1", restaurant_brand="BRAND-1", cashier_session="SESSION-1", status="Confirmed",
			pos_invoice=None, customer="CUSTOMER-1", subtotal=81.49, grand_total=80.49, items=[frappe._dict(name="LINE-1", item="ITEM-1",
				qty=1, cancelled_qty=0, uom="Nos", selling_price=80.49, warehouse=None,
				modifiers=frappe.as_json([{"modifier_product": "MODIFIER-1", "qty": 1, "selling_price": 1, "warehouse": None}]))], payments=[],
			discount_scope="Net Total", discount_amount=0, discount_type="Percentage", discount_value=0,
			sales_taxes_and_charges_template=None, order_type="Dine In", save=unittest.mock.Mock(),
			validate_discount=unittest.mock.Mock(),
			flags=frappe._dict())
		order.calculate_tax_preview = lambda apply_discount=False: (0, 80.49 if apply_discount else 81.49)
		order.append = lambda fieldname, row: getattr(order, fieldname).append(frappe._dict(row))
		session = frappe._dict(name="SESSION-1", user="cashier@example.com", status="Open",
			pos_profile="PROFILE-1", pos_opening_entry="OPENING-1")
		profile = frappe._dict(name="PROFILE-1", customer="CUSTOMER-1", company="COMPANY-1", selling_price_list="PRICE-LIST-1", update_stock=0)
		invoice = SimpleNamespace(name="POSINV-1", items=[], payments=[], taxes=[], grand_total=80.49, rounded_total=81,
			change_amount=0, flags=frappe._dict(),
			set_missing_values=unittest.mock.Mock(), set_missing_item_details=unittest.mock.Mock(),
			calculate_taxes_and_totals=unittest.mock.Mock(), add_comment=unittest.mock.Mock(), submit=unittest.mock.Mock(),
			validate_pos_opening_entry=unittest.mock.Mock(side_effect=AssertionError("unscoped ERPNext date validator ran")))
		invoice.set = lambda fieldname, value: setattr(invoice, fieldname, value)
		def append_invoice_row(fieldname, values):
			row = frappe._dict(values)
			getattr(invoice, fieldname).append(row)
			return row
		invoice.append = append_invoice_row
		invoice.insert = unittest.mock.Mock(side_effect=lambda **kwargs: invoice.validate_pos_opening_entry())
		invoice.submit.side_effect = lambda: invoice.validate_pos_opening_entry()
		opening = frappe._dict(name="OPENING-1", pos_profile="PROFILE-1", user="cashier@example.com",
			company="COMPANY-1", status="Open", docstatus=1, period_start_date="2026-10-19 14:39:00")

		def get_doc(doctype, name=None, *args, **kwargs):
			if doctype == "POS Order":
				return order
			if doctype == "Cashier Session":
				return session
			if doctype == "POS Profile":
				return profile
			if doctype == "Store":
				return frappe._dict(manual_discount_scope="Net Total")
			if doctype == "Selling Product" and name == "MODIFIER-1":
				return frappe._dict(item="MOD-ITEM-1", uom="Nos", maintain_stock=0)
			self.fail(f"Unexpected document lookup: {doctype} {name}")

		def get_value(doctype, *args, **kwargs):
			if doctype == "Restaurant Brand":
				return "Round Up"
			if doctype == "Cashier Session":
				return "cashier@example.com"
			if doctype == "Item":
				fieldname = args[-1] if args else kwargs.get("fieldname")
				item_code = args[0] if args else kwargs.get("filters")
				item_names = {"ITEM-1": "Coffee", "MOD-ITEM-1": "Mocha"}
				return {"item_name": item_names.get(item_code), "stock_uom": "Nos", "is_stock_item": 0}.get(fieldname)
			if doctype == "Order Type Account Mapping":
				return frappe._dict(income_account="INCOME-1", cost_of_goods_sold_account="COGS-1")
			return None

		with patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.assert_store_access"), \
				patch("rms.api.pos.require_order_scope"), \
				patch("rms.api.pos.session_payment_rows", return_value=[frappe._dict(mode_of_payment="Cash")]), \
				patch("rms.api.pos.frappe.get_doc", side_effect=get_doc), \
				patch("rms.api.pos.frappe.get_all", return_value=[opening]), \
				patch("rms.api.pos.frappe.db.get_value", side_effect=get_value), \
				patch("rms.api.pos.frappe.db.set_value"), \
				patch("rms.api.pos.frappe.new_doc", return_value=invoice), \
			patch("rms.api.pos.get_pos_discount_approval", side_effect=["manager@example.com", "manager@example.com"]) as verify_discount_approval, \
				patch("rms.api.pos.create_recipe_stock_entry", return_value=None), \
				patch("rms.api.pos.nowdate", return_value="2026-10-20"), \
				patch("rms.taxes.nowdate", return_value="2026-10-20"), \
				patch("rms.api.pos.frappe.set_user"), \
				patch("rms.api.pos.frappe.session", frappe._dict(user="cashier@example.com")):
			result = pay_order("ORDER-1", '[{"mode_of_payment":"Cash","amount":81}]', discount_type="Amount",
				discount_value=1, discount_reason="Service recovery", discount_approval_code="381604",
				discount_approval_approver="manager@example.com")

		self.assertEqual(result["status"], "Paid")
		self.assertEqual(invoice.items[0].item_name, "Coffee")
		self.assertEqual(invoice.items[1].item_name, "Mocha")
		self.assertEqual(invoice.items[0].conversion_factor, 1)
		self.assertEqual(invoice.items[1].conversion_factor, 1)
		self.assertEqual(invoice.flags.rms_pos_rounding_method, "Round Up")
		self.assertEqual(invoice.payments[0].amount, 81)
		self.assertEqual(invoice.rounded_total, 81)
		self.assertEqual(verify_discount_approval.call_count, 2)
		self.assertEqual(verify_discount_approval.call_args_list[0].kwargs["approval_approver"], "manager@example.com")
		self.assertEqual(verify_discount_approval.call_args_list[1].kwargs["approval_approver"], "manager@example.com")
		invoice.insert.assert_called_once_with(ignore_permissions=True)
		invoice.submit.assert_called_once_with()
		self.assertEqual(order.pos_invoice, "POSINV-1")

	def test_recipe_stock_entry_uses_only_active_order_qty_after_partial_cancellation(self):
		order = SimpleNamespace(name="ORDER-RECIPE-1", recipe_stock_entry=None, items=[
			frappe._dict(qty=2, cancelled_qty=0.5, recipe_snapshot=frappe.as_json([
				{"item": "COFFEE-BEANS", "qty": 0.08, "uom": "Kg", "warehouse": "Main"},
				{"item": "WHOLE-MILK", "qty": 0.4, "uom": "L", "warehouse": "Main"},
			])),
			frappe._dict(qty=1, cancelled_qty=1, recipe_snapshot=frappe.as_json([
				{"item": "VANILLA-SYRUP", "qty": 0.02, "uom": "L", "warehouse": "Main"},
			])),
		])
		with patch("rms.api.pos.create_material_issue", return_value="STE-1") as create_issue:
			result = create_recipe_stock_entry(order, "COMPANY-1", "COGS-1")
		self.assertEqual(result, "STE-1")
		components = create_issue.call_args.args[1]
		self.assertEqual([row.item for row in components], ["COFFEE-BEANS", "WHOLE-MILK"])
		self.assertAlmostEqual(components[0].qty, 0.06)
		self.assertAlmostEqual(components[1].qty, 0.3)
		self.assertNotIn("VANILLA-SYRUP", [row.item for row in components])
	def test_paid_order_payment_retry_returns_existing_invoice_without_creating_invoice(self):
		order = frappe._dict(name="ORDER-1", store="STORE-1", cashier_session="SESSION-1", status="Paid",
			pos_invoice="POSINV-1")
		with patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.assert_store_access"), \
				patch("rms.api.pos.require_order_scope"), \
				patch("rms.api.pos.frappe.get_doc", return_value=order) as get_doc, \
				patch("rms.api.pos.frappe.db.get_value", return_value="cashier@example.com"), \
				patch("rms.api.pos.frappe.new_doc") as new_doc, \
				patch("rms.api.pos.frappe.session", frappe._dict(user="cashier@example.com")):
			result = pay_order("ORDER-1", '[{"mode_of_payment":"Cash","amount":10}]')
		self.assertEqual(result, {"pos_invoice": "POSINV-1", "status": "Paid"})
		get_doc.assert_called_once_with("POS Order", "ORDER-1", for_update=True)
		new_doc.assert_not_called()
	def test_pay_order_rejects_a_different_cashier_before_creating_an_invoice(self):
		order = frappe._dict(name="ORDER-1", store="STORE-1", cashier_session="OWNER-SESSION", status="Confirmed")
		with patch("rms.api.pos.require_pos_action"), \
				patch("rms.api.pos.frappe.get_doc", return_value=order), \
				patch("rms.api.pos.assert_store_access"), patch("rms.api.pos.require_order_scope"), \
				patch("rms.api.pos.frappe.db.get_value", return_value="owner@example.com"), \
				patch("rms.api.pos.frappe.new_doc") as new_doc, \
				patch("frappe.session", frappe._dict(user="editor@example.com")):
			with self.assertRaisesRegex(frappe.PermissionError, "another Cashier Session"):
				pay_order("ORDER-1", '[{"mode_of_payment":"Cash","amount":10}]')
		new_doc.assert_not_called()

	def test_split_payment_rejects_more_than_ten_guest_checks(self):
		with self.assertRaisesRegex(frappe.ValidationError, "between two and ten guest checks"):
			self._call_pay_order_with_guest_rows([
				{"guest": f"Guest {number}", "mode_of_payment": "Cash", "amount": 1}
				for number in range(1, 12)
			])

	def test_sales_history_for_cashier_is_limited_to_all_their_sessions(self):
		filters = get_pos_sales_history_filters("STORE-1", "cashier@example.com", {"POS Cashier"}, ["SESSION-1", "SESSION-2"])
		self.assertEqual(filters["store"], "STORE-1")
		self.assertEqual(filters["status"], "Paid")
		self.assertEqual(filters["cashier_session"], ["in", ["SESSION-1", "SESSION-2"]])

	def test_sales_history_for_manager_is_store_scoped_without_session_restriction(self):
		filters = get_pos_sales_history_filters("STORE-1", "manager@example.com", {"POS Manager"}, [])
		self.assertEqual(filters, {"store": "STORE-1", "status": "Paid", "pos_invoice": ["is", "set"]})

	def test_sales_history_hides_cashier_invoices_when_they_have_no_sessions(self):
		self.assertIsNone(get_pos_sales_history_filters("STORE-1", "cashier@example.com", {"POS Cashier"}, []))

	def test_sales_history_rejects_users_without_pos_role(self):
		with self.assertRaisesRegex(frappe.PermissionError, "not allowed to view POS sales history"):
			get_pos_sales_history_filters("STORE-1", "staff@example.com", {"Kitchen Operator"}, [])

	def test_receipt_reprint_renders_paid_invoice_without_creating_another_sale(self):
		order = frappe._dict(name="ORDER-1", store="STORE-1", status="Paid", pos_invoice="POSINV-1",
			cashier_session="SESSION-1", restaurant_brand="BRAND-1", order_type="Takeaway")
		invoice = frappe._dict(docstatus=1)
		with patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.assert_store_access"), \
				patch("rms.api.pos.require_order_scope"), patch("rms.api.pos.frappe.get_doc", side_effect=[order, invoice]), \
				patch("rms.api.pos.frappe.get_roles", return_value=["POS Cashier"]), \
				patch("rms.api.pos.frappe.session", frappe._dict(user="cashier@example.com")), \
				patch("rms.api.pos.frappe.get_all", return_value=["SESSION-1"]), \
				patch("rms.api.pos.frappe.set_user") as set_user, \
				patch("rms.api.pos.frappe.get_print", return_value="<html>receipt</html>") as get_print, \
				patch("rms.api.pos.frappe.new_doc") as new_doc:
			result = get_pos_invoice_print_html("ORDER-1")
		self.assertEqual(result, "<html>receipt</html>")
		get_print.assert_called_once_with("POS Invoice", "POSINV-1", print_format="Standard", no_letterhead=1)
		self.assertEqual([call.args[0] for call in set_user.call_args_list], ["Administrator", "cashier@example.com"])
		new_doc.assert_not_called()

	def test_cashier_cannot_reprint_another_sessions_invoice(self):
		order = frappe._dict(name="ORDER-1", store="STORE-1", status="Paid", pos_invoice="POSINV-1",
			cashier_session="OTHER-SESSION", restaurant_brand="BRAND-1", order_type="Takeaway")
		with patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.assert_store_access"), \
				patch("rms.api.pos.require_order_scope"), patch("rms.api.pos.frappe.get_doc", return_value=order) as get_doc, \
				patch("rms.api.pos.frappe.get_roles", return_value=["POS Cashier"]), \
				patch("rms.api.pos.frappe.session", frappe._dict(user="cashier@example.com")), \
				patch("rms.api.pos.frappe.get_all", return_value=["SESSION-1"]), \
				patch("rms.api.pos.frappe.get_print") as get_print:
			with self.assertRaisesRegex(frappe.PermissionError, "own cashier sessions"):
				get_pos_invoice_print_html("ORDER-1")
		self.assertEqual(get_doc.call_count, 1)
		get_print.assert_not_called()

	def test_pos_user_capability_defaults_keep_legacy_pos_roles_working(self):
		with patch("rms.api.pos.get_active_pos_user", return_value=None):
			capabilities = get_pos_capabilities("cashier@example.com")
		self.assertTrue(all(value for name, value in capabilities.items() if name != "can_approve_discount"))
		self.assertFalse(capabilities["can_approve_discount"])

	def test_disabled_pos_user_capability_blocks_api_action(self):
		values = {fieldname: 1 for fieldname in (
			"can_view_tables", "can_view_open_orders", "can_view_sales_history", "can_reprint_receipts",
			"can_checkout", "can_apply_manual_discount", "can_cancel_orders", "can_transfer_tables",
			"can_split_orders", "can_merge_orders", "can_request_returns", "can_access_kitchen",
			"can_prepare_orders", "can_pick_orders", "can_acknowledge_cancellations",
		)}
		values["can_split_orders"] = 0
		with patch("rms.api.pos.frappe.get_roles", return_value=["POS Cashier"]), \
				patch("rms.api.pos.frappe.session", frappe._dict(user="cashier@example.com")), \
				patch("rms.api.pos.get_active_pos_user", return_value="POS-USER-1"), \
				patch("rms.api.pos.frappe.db.get_value", return_value=frappe._dict(values)):
			with self.assertRaisesRegex(frappe.PermissionError, "permissions do not allow"):
				require_pos_action("can_split_orders")

	def test_disabled_kitchen_capability_blocks_kitchen_action(self):
		with patch("rms.api.pos.require_kitchen_role"), \
				patch("rms.api.pos.get_pos_capabilities", return_value={"can_access_kitchen": False}):
			with self.assertRaisesRegex(frappe.PermissionError, "permissions do not allow"):
				require_kitchen_capability("can_access_kitchen")

	def test_pos_cashier_cannot_change_kitchen_ticket_status(self):
		with patch("frappe.session", frappe._dict(user="cashier@example.com")), \
				patch("frappe.get_roles", return_value=["POS Cashier"]), \
				patch("rms.api.pos.require_pos_capability"), \
				patch("frappe.get_doc") as get_doc:
			with self.assertRaisesRegex(frappe.PermissionError, "Kitchen ticket changes require"):
				set_kitchen_ticket_status("TICKET-1", "Started")

		get_doc.assert_not_called()

	def test_table_map_identifies_available_and_occupied_tables(self):
		tables = [
			frappe._dict(name="TABLE-1", title="Patio 01", dining_area="AREA-1", capacity=2, sequence_id=1),
			frappe._dict(name="TABLE-2", title="Patio 02", dining_area="AREA-1", capacity=4, sequence_id=2),
		]
		orders = [frappe._dict(name="ORDER-1", dining_table="TABLE-2", status="Confirmed", cashier_session="SESSION-1", restaurant_brand="BRAND-1", order_type="Dine In", grand_total=115, modified="2026-10-19 12:00:00")]
		sessions = [frappe._dict(name="SESSION-1", user="cashier@example.com")]
		users = [frappe._dict(name="cashier@example.com", full_name="Cashier One")]
		areas = [frappe._dict(name="AREA-1", title="Garden Patio")]
		with patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.assert_store_access"), patch("rms.api.pos.get_pos_capabilities", return_value={"can_view_open_orders": True}), patch("rms.api.pos.is_pos_scope_allowed", return_value=True), \
				patch("rms.api.pos.frappe.get_all", side_effect=[tables, orders, sessions, users, areas]):
			result = get_tables("STORE-1")
		self.assertFalse(result[0].occupied)
		self.assertEqual(result[0].dining_area_title, "Garden Patio")
		self.assertTrue(result[1].occupied)
		self.assertEqual(result[1].open_order, {
			"order": "ORDER-1", "status": "Confirmed", "cashier_session": "SESSION-1", "cashier": "Cashier One",
			"check_label": None, "order_type": "Dine In", "grand_total": 115, "modified": "2026-10-19 12:00:00",
		})

	def test_store_open_orders_can_be_viewed_without_an_active_cashier_session(self):
		orders = [frappe._dict(name="ORDER-1", status="Confirmed", order_type="Dine In", dining_table="TABLE-1",
			business_date="2026-10-19", grand_total=125, modified="2026-10-19 12:00:00", cashier_session="SESSION-1")]
		sessions = [frappe._dict(name="SESSION-1", user="other.cashier@example.com")]
		users = [frappe._dict(name="other.cashier@example.com", full_name="Other Cashier")]
		items = [frappe._dict(parent="ORDER-1", sent_to_kitchen=1, qty=1, cancelled_qty=0),
			frappe._dict(parent="ORDER-1", sent_to_kitchen=0, qty=1, cancelled_qty=0),
			frappe._dict(parent="ORDER-1", sent_to_kitchen=1, qty=1, cancelled_qty=1)]
		with patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.assert_store_access"), patch("rms.api.pos.is_pos_scope_allowed", return_value=True), \
				patch("rms.api.pos.frappe.get_all", side_effect=[orders, sessions, users, items]):
			result = get_store_open_orders("STORE-1")
		self.assertEqual(result[0].cashier, "Other Cashier")
		self.assertEqual(result[0].item_count, 2)
		self.assertEqual(result[0].sent_item_count, 1)
		self.assertEqual(result[0].pending_item_count, 1)

	def test_open_order_overview_is_read_only_and_does_not_require_session_ownership(self):
		order = frappe._dict(name="ORDER-1", status="Confirmed", store="STORE-1", cashier_session="SESSION-1",
			restaurant_brand="BRAND-1", order_type="Dine In", customer="Walk-in", dining_area="AREA-1",
			dining_table="TABLE-1", subtotal=100, discount_amount=0, discount_type="Percentage",
			discount_scope="Net Total", tax_total=15, grand_total=115,
			items=[frappe._dict(selling_product="PRODUCT-1", qty=1, uom="Nos", selling_price=100, amount=100, modifiers="[]")])
		with patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.assert_store_access"), patch("rms.api.pos.require_order_scope"), \
				patch("rms.api.pos.frappe.get_doc", return_value=order), \
				patch("rms.api.pos.frappe.db.get_value", side_effect=["other.cashier@example.com", "Classic Koshari"]):
			result = get_open_order_overview("ORDER-1")
		self.assertEqual(result["cashier"], "other.cashier@example.com")
		self.assertEqual(result["items"][0]["title"], "Classic Koshari")
		self.assertEqual(result["grand_total"], 115)

	def test_disabled_pos_user_cannot_fall_back_to_legacy_access(self):
		with patch("rms.api.pos.frappe.db.get_value", return_value=None), \
				patch("rms.api.pos.frappe.db.exists", return_value=True):
			with self.assertRaisesRegex(frappe.PermissionError, "POS User account is disabled"):
				get_active_pos_user("cashier@example.com")

	def test_pos_user_store_assignment_is_enforced(self):
		store = frappe._dict(name="STORE-1", enabled=1, pos_profile="PROFILE-1", company="COMPANY-1")
		with patch("rms.api.pos.frappe.db.get_value", side_effect=[store, "POS-USER-1"]), \
				patch("rms.api.pos.frappe.db.exists", return_value=False), \
				patch("frappe.session", frappe._dict(user="cashier@example.com")):
			with self.assertRaisesRegex(frappe.PermissionError, "not assigned to this Store"):
				assert_store_access("STORE-1")

	def test_pos_user_can_access_assigned_store(self):
		store = frappe._dict(name="STORE-1", enabled=1, pos_profile="PROFILE-1", company="COMPANY-1")
		with patch("rms.api.pos.frappe.db.get_value", side_effect=[store, "POS-USER-1"]), \
				patch("rms.api.pos.frappe.db.exists", return_value=True), \
				patch("frappe.session", frappe._dict(user="cashier@example.com")):
			self.assertEqual(assert_store_access("STORE-1"), store)

	def test_empty_pos_user_allowlist_means_unrestricted_scope(self):
		with patch("rms.api.pos.get_active_pos_user", return_value="POS-USER-1"), patch("rms.api.pos.frappe.get_all", return_value=[]):
			self.assertIsNone(get_pos_user_scope_values("brand"))
			self.assertTrue(is_pos_scope_allowed("brand", "BRAND-1"))

	def test_selected_pos_user_scope_rejects_unlisted_value(self):
		with patch("rms.api.pos.get_pos_user_scope_values", return_value={"BRAND-1"}), patch("rms.api.pos.frappe.throw", side_effect=frappe.PermissionError):
			with self.assertRaises(frappe.PermissionError):
				require_pos_scope("brand", "BRAND-2")

	def test_preparation_area_has_ordering_field_used_by_kitchen_board(self):
		self.assertIsNotNone(frappe.get_meta("Preparation Area").get_field("sequence_id"))

	def test_kitchen_board_uses_store_scoped_internal_reads_for_kitchen_role(self):
		areas = [frappe._dict(name="HOT", title="Hot Kitchen", sequence_id=1)]
		tickets = [frappe._dict(name="TICKET-1", pos_order="ORDER-1", preparation_area="HOT", status="Pending")]
		with patch("rms.api.pos.require_kitchen_capability"), patch("rms.api.pos.assert_store_access"), patch("rms.api.pos.get_pos_user_scope_values", return_value=None), patch("rms.api.pos.is_pos_scope_allowed", return_value=True), \
				patch("frappe.get_all", side_effect=[areas, tickets, []]) as get_all, \
				patch("rms.api.pos.get_pos_capabilities", return_value={"can_prepare_orders": True, "can_pick_orders": True, "can_acknowledge_cancellations": True}), \
				patch("frappe.get_roles", return_value=["Kitchen Operator"]), \
				patch("frappe.get_doc", return_value=frappe._dict(order_type="Dine In", dining_table="Table 01")), \
				patch("frappe.db.get_value", return_value="Koshari Classic"):
			board = get_kitchen_board("STORE-1")
		self.assertEqual(len(board["tickets"]), 1)
		self.assertTrue(all(call.kwargs.get("ignore_permissions") for call in get_all.call_args_list))

	def test_kitchen_board_hides_mutation_capabilities_from_cashier_without_kitchen_role(self):
		areas = [frappe._dict(name="BEV", title="Beverage Counter", sequence_id=1)]
		capabilities = {"can_prepare_orders": True, "can_pick_orders": True,
			"can_acknowledge_cancellations": True}
		with patch("rms.api.pos.require_kitchen_capability"), patch("rms.api.pos.assert_store_access"), \
				patch("rms.api.pos.get_pos_user_scope_values", return_value=None), \
				patch("frappe.get_all", side_effect=[areas, []]), \
				patch("rms.api.pos.get_pos_capabilities", return_value=capabilities), \
				patch("frappe.get_roles", return_value=["POS Cashier"]):
			board = get_kitchen_board("STORE-1")

		self.assertEqual(board["permissions"], {key: False for key in capabilities})

	def test_kitchen_operator_capabilities_are_available_on_kitchen_board(self):
		areas = [frappe._dict(name="BEV", title="Beverage Counter", sequence_id=1)]
		capabilities = {"can_prepare_orders": True, "can_pick_orders": True,
			"can_acknowledge_cancellations": True}
		with patch("rms.api.pos.require_kitchen_capability"), patch("rms.api.pos.assert_store_access"), \
				patch("rms.api.pos.get_pos_user_scope_values", return_value=None), \
				patch("frappe.get_all", side_effect=[areas, []]), \
				patch("rms.api.pos.get_pos_capabilities", return_value=capabilities), \
				patch("frappe.get_roles", return_value=["Kitchen Operator"]):
			board = get_kitchen_board("STORE-1")

		self.assertEqual(board["permissions"], capabilities)

	def test_kitchen_board_includes_unacknowledged_cancellation_notices(self):
		areas = [frappe._dict(name="HOT", title="Hot Kitchen", sequence_id=1)]
		tickets = [frappe._dict(name="TICKET-1", pos_order="ORDER-1", preparation_area="HOT", status="Cancelled")]
		with patch("rms.api.pos.require_kitchen_capability"), patch("rms.api.pos.assert_store_access"), patch("rms.api.pos.get_pos_user_scope_values", return_value=None), patch("rms.api.pos.is_pos_scope_allowed", return_value=True), \
				patch("frappe.get_all", side_effect=[areas, tickets, []]) as get_all, \
				patch("rms.api.pos.get_pos_capabilities", return_value={"can_prepare_orders": True, "can_pick_orders": True, "can_acknowledge_cancellations": True}), \
				patch("frappe.get_roles", return_value=["Kitchen Operator"]), \
				patch("frappe.get_doc", return_value=frappe._dict(order_type="Dine In", dining_table="Table 01")):
			board = get_kitchen_board("STORE-1")
		ticket_query = get_all.call_args_list[1].kwargs
		self.assertIn("Cancelled", ticket_query["filters"]["status"][1])
		self.assertEqual(ticket_query["filters"]["cancellation_acknowledged_at"], ["is", "not set"])
		self.assertEqual(board["tickets"][0]["status"], "Cancelled")

	def test_kitchen_operator_can_acknowledge_cancelled_ticket(self):
		ticket = frappe.new_doc("Kitchen Ticket")
		ticket.name = "TICKET-1"
		ticket.store = "STORE-1"
		ticket.status = "Cancelled"
		ticket.cancellation_acknowledged_at = None
		ticket.cancellation_acknowledged_by = None
		ticket.save = unittest.mock.Mock()
		with patch("rms.api.pos.require_kitchen_role"), patch("rms.api.pos.require_pos_capability"), patch("rms.api.pos.assert_store_access"), patch("rms.api.pos.require_order_scope"), \
				patch("frappe.get_doc", return_value=ticket), patch("frappe.get_roles", return_value=["Kitchen Operator"]), \
				patch("frappe.session", frappe._dict(user="omar@example.com")), \
				patch("rms.api.pos.now_datetime", return_value="2026-10-20 12:00:00"), \
				patch("frappe.db.set_value") as set_value:
			try:
				result = set_kitchen_ticket_status("TICKET-1", "Acknowledge Cancellation")
			except frappe.ValidationError:
				result = None
		self.assertEqual(result, {"name": "TICKET-1", "status": "Cancelled", "acknowledged": True})
		self.assertEqual(ticket.cancellation_acknowledged_by, "omar@example.com")
		self.assertTrue(ticket.cancellation_acknowledged_at)
		set_value.assert_called_once_with("Kitchen Ticket", "TICKET-1", {
			"cancellation_acknowledged_at": ticket.cancellation_acknowledged_at,
			"cancellation_acknowledged_by": "omar@example.com",
		})
		ticket.save.assert_not_called()

	def test_active_kitchen_ticket_cannot_acknowledge_a_cancellation(self):
		ticket = frappe.new_doc("Kitchen Ticket")
		ticket.name = "TICKET-1"
		ticket.store = "STORE-1"
		ticket.status = "Started"
		with patch("rms.api.pos.require_kitchen_role"), patch("rms.api.pos.require_pos_capability"), patch("rms.api.pos.assert_store_access"), patch("rms.api.pos.require_order_scope"), \
				patch("frappe.get_doc", return_value=ticket), patch("frappe.get_roles", return_value=["Kitchen Operator"]), \
				patch("frappe.session", frappe._dict(user="omar@example.com")), patch("frappe.db.set_value") as set_value:
			with self.assertRaisesRegex(frappe.ValidationError, "Only cancelled Kitchen Tickets can acknowledge"):
				set_kitchen_ticket_status("TICKET-1", "Acknowledge Cancellation")

	def test_repeated_cancellation_acknowledgement_preserves_original_acknowledger(self):
		ticket = frappe.new_doc("Kitchen Ticket")
		ticket.name = "TICKET-1"
		ticket.store = "STORE-1"
		ticket.status = "Cancelled"
		ticket.cancellation_acknowledged_at = frappe.utils.now_datetime()
		ticket.cancellation_acknowledged_by = "salma@example.com"
		ticket.save = unittest.mock.Mock()
		with patch("rms.api.pos.require_kitchen_role"), patch("rms.api.pos.require_pos_capability"), patch("rms.api.pos.assert_store_access"), patch("rms.api.pos.require_order_scope"), \
				patch("frappe.get_doc", return_value=ticket), patch("frappe.get_roles", return_value=["Kitchen Operator"]), \
				patch("frappe.session", frappe._dict(user="omar@example.com")), patch("frappe.db.set_value") as set_value:
			try:
				result = set_kitchen_ticket_status("TICKET-1", "Acknowledge Cancellation")
			except frappe.ValidationError:
				result = None
		self.assertEqual(result, {"name": "TICKET-1", "status": "Cancelled", "acknowledged": True})
		self.assertEqual(ticket.cancellation_acknowledged_by, "salma@example.com")
		set_value.assert_not_called()

	def test_kitchen_ticket_status_recalculation_reads_sibling_tickets_internally(self):
		ticket = frappe.new_doc("Kitchen Ticket")
		ticket.pos_order = "ORDER-1"
		order = frappe._dict(set_kitchen_status=lambda status: None)
		with patch("frappe.get_doc", return_value=order), patch("frappe.get_all", return_value=[frappe._dict(status="Started")]) as get_all:
			KitchenTicket.update_order_status(ticket)
		self.assertTrue(get_all.call_args.kwargs.get("ignore_permissions"))

	def test_store_access_context_includes_store_name_for_session_and_order_creation(self):
		store = frappe._dict(name="STORE-1", enabled=1, pos_profile="PROFILE-1", company="COMPANY-1")
		with patch("frappe.db.get_value", side_effect=[store, None]) as get_value, \
				patch("frappe.db.exists", return_value=False), \
				patch("frappe.get_all", return_value=[]), \
				patch("frappe.session", frappe._dict(user="cashier@example.com")):
			self.assertEqual(assert_store_access("STORE-1").name, "STORE-1")
		self.assertEqual(get_value.call_args_list[0].args[:2], ("Store", "STORE-1"))

	def test_confirmed_order_cannot_be_changed_by_draft_operations(self):
		order = frappe._dict(name="ORDER-1", store="STORE-1", status="Confirmed")
		with patch("rms.api.pos.require_pos_role"), patch("frappe.get_doc", return_value=order), \
				patch("rms.api.pos.assert_store_access"):
			with self.assertRaisesRegex(frappe.ValidationError, "not available for the current order status"):
				get_owned_draft_order("ORDER-1")

	def test_open_order_editor_can_confirm_items_added_to_another_cashiers_order(self):
		order = frappe._dict(name="ORDER-1", store="STORE-1", cashier_session="OWNER-SESSION", flags=frappe._dict(), confirm=unittest.mock.Mock())
		with patch("rms.api.pos.require_pos_action") as require_action, \
				patch("rms.api.pos.frappe.get_doc", return_value=order), \
				patch("rms.api.pos.assert_store_access"), patch("rms.api.pos.require_order_scope"), \
				patch("rms.api.pos.frappe.db.get_value", return_value="owner@example.com"), \
				patch("rms.api.pos.get_user_session", return_value=frappe._dict(status="Open")), \
				patch("frappe.get_all", return_value=["TICKET-1"]), \
				patch("frappe.session", frappe._dict(user="editor@example.com")):
			result = confirm_order("ORDER-1")
		self.assertEqual(result, {"name": "ORDER-1", "status": None, "tickets": ["TICKET-1"]})
		order.confirm.assert_called_once_with()
		require_action.assert_any_call("can_checkout")
		require_action.assert_any_call("can_edit_open_orders")

	def test_cross_session_order_cannot_be_confirmed_without_an_open_session(self):
		order = frappe._dict(name="ORDER-1", store="STORE-1", cashier_session="OWNER-SESSION", flags=frappe._dict(), confirm=unittest.mock.Mock())
		with patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.frappe.get_doc", return_value=order), \
				patch("rms.api.pos.assert_store_access"), patch("rms.api.pos.require_order_scope"), \
				patch("rms.api.pos.frappe.db.get_value", return_value="owner@example.com"), \
				patch("rms.api.pos.get_user_session", return_value=None), \
				patch("frappe.session", frappe._dict(user="editor@example.com")):
			with self.assertRaisesRegex(frappe.PermissionError, "Open your Cashier Session"):
				confirm_order("ORDER-1")
		order.confirm.assert_not_called()

	def test_draft_order_must_belong_to_the_current_open_session(self):
		order = frappe._dict(name="ORDER-1", store="STORE-1", status="Open", cashier_session="SESSION-OTHER")
		with patch("rms.api.pos.require_pos_role"), patch("frappe.get_doc", return_value=order), \
				patch("rms.api.pos.assert_store_access"), patch("frappe.session", frappe._dict(user="cashier@example.com")), \
				patch("frappe.db.get_value", return_value="SESSION-CURRENT"):
			with self.assertRaises(frappe.PermissionError):
				get_owned_draft_order("ORDER-1")

	def test_cancel_order_reloads_after_ticket_updates_before_saving(self):
		order = frappe._dict(name="ORDER-1", store="STORE-1", cashier_session="SESSION-1", status="Ready",
			flags=frappe._dict(), reload=unittest.mock.Mock(), save=unittest.mock.Mock())
		with patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.assert_store_access"), \
				patch("rms.api.pos.frappe.get_doc", return_value=order), \
				patch("rms.api.pos.frappe.db.get_value", return_value="cashier@example.com"), \
				patch("rms.api.pos.frappe.get_roles", return_value=["POS Manager"]), \
				patch("rms.api.pos.frappe.get_all", return_value=[]), \
				patch("frappe.session", frappe._dict(user="cashier@example.com")):
			cancel_order("ORDER-1")
		order.reload.assert_called_once_with()

	def test_pos_manager_can_cancel_confirmed_order_from_cashiers_session(self):
		order = frappe._dict(name="ORDER-1", store="STORE-1", cashier_session="SESSION-1", status="Ready",
			flags=frappe._dict(), reload=unittest.mock.Mock(), save=unittest.mock.Mock())
		with patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.assert_store_access"), \
				patch("rms.api.pos.frappe.get_doc", return_value=order), \
				patch("rms.api.pos.frappe.db.get_value", return_value="mariam@example.com"), \
				patch("rms.api.pos.frappe.get_roles", return_value=["POS Manager"]), \
				patch("rms.api.pos.frappe.get_all", return_value=[]), \
				patch("frappe.session", frappe._dict(user="salma@example.com")):
			try:
				result = cancel_order("ORDER-1")
			except frappe.PermissionError:
				result = None
		self.assertEqual(result, {"name": "ORDER-1", "status": "Cancelled"})

	def test_confirmed_item_cancellation_is_manager_only(self):
		with patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.frappe.get_roles", return_value=["POS Cashier"]):
			with self.assertRaisesRegex(frappe.PermissionError, "POS Manager"):
				cancel_confirmed_order_item("ORDER-1", "ROW-1", 1, "Customer changed mind")

	def test_confirmed_guest_split_locks_order_item_cancellation(self):
		order = frappe._dict(name="ORDER-1", store="STORE-1", cashier_session="SESSION-1", items=[],
			guest_checks=[frappe._dict(status="Open")])
		with patch("rms.api.pos.require_pos_action"), patch("rms.api.pos.frappe.get_doc", return_value=order), \
				patch("rms.api.pos.assert_store_access"), patch("rms.api.pos.require_order_scope"), \
				patch("rms.api.pos.frappe.get_roles", return_value=["POS Manager"]):
			with self.assertRaisesRegex(frappe.ValidationError, "Items cannot be changed after guest checks are confirmed"):
				cancel_confirmed_order_item("ORDER-1", "ROW-1", 1, "Customer changed mind")

	def test_unsent_order_item_comment_is_saved_for_same_cashier(self):
		row = frappe._dict(name="ROW-1", sent_to_kitchen=0)
		order = frappe._dict(name="ORDER-1", store="STORE-1", cashier_session="SESSION-1", status="Confirmed",
			restaurant_brand="BRAND-1", order_type="Dine In", items=[row])
		with patch("rms.api.pos.require_pos_action") as require_action, \
				patch("rms.api.pos.frappe.get_doc", return_value=order), \
				patch("rms.api.pos.assert_store_access"), patch("rms.api.pos.require_order_scope"), \
				patch("rms.api.pos.get_user_session", return_value=frappe._dict(name="SESSION-1", status="Open")), \
				patch("rms.api.pos.frappe.db.set_value") as set_value:
			result = update_order_item_notes("ORDER-1", "ROW-1", "بدون ثلج")
		self.assertEqual(result, {"name": "ROW-1", "notes": "بدون ثلج"})
		require_action.assert_called_once_with("can_checkout")
		set_value.assert_called_once_with("POS Order Item", "ROW-1", "notes", "بدون ثلج", update_modified=True)

	def test_unsent_order_item_comment_requires_open_order_edit_capability_cross_session(self):
		row = frappe._dict(name="ROW-1", sent_to_kitchen=0)
		order = frappe._dict(name="ORDER-1", store="STORE-1", cashier_session="OTHER-SESSION", status="Confirmed",
			restaurant_brand="BRAND-1", order_type="Dine In", items=[row])
		with patch("rms.api.pos.require_pos_action") as require_action, \
				patch("rms.api.pos.frappe.get_doc", return_value=order), \
				patch("rms.api.pos.assert_store_access"), patch("rms.api.pos.require_order_scope"), \
				patch("rms.api.pos.get_user_session", return_value=frappe._dict(name="SESSION-1", status="Open")), \
				patch("rms.api.pos.frappe.db.set_value"):
			update_order_item_notes("ORDER-1", "ROW-1", "No ice")
		require_action.assert_any_call("can_checkout")
		require_action.assert_any_call("can_edit_open_orders")

	def test_sent_order_item_comment_is_rejected(self):
		row = frappe._dict(name="ROW-1", sent_to_kitchen=1)
		order = frappe._dict(name="ORDER-1", store="STORE-1", cashier_session="SESSION-1", status="Confirmed",
			restaurant_brand="BRAND-1", order_type="Dine In", items=[row])
		with patch("rms.api.pos.require_pos_action"), \
				patch("rms.api.pos.frappe.get_doc", return_value=order), \
				patch("rms.api.pos.assert_store_access"), patch("rms.api.pos.require_order_scope"), \
				patch("rms.api.pos.get_user_session", return_value=frappe._dict(name="SESSION-1", status="Open")), \
				patch("rms.api.pos.frappe.db.set_value") as set_value:
			with self.assertRaisesRegex(frappe.PermissionError, "already sent"):
				update_order_item_notes("ORDER-1", "ROW-1", "Late request")
		set_value.assert_not_called()

	def test_kitchen_item_cancellation_does_not_overwrite_order_status_during_save(self):
		ticket = frappe.new_doc("Kitchen Ticket")
		ticket.status = "Ready"
		ticket.flags.skip_order_status_sync = True
		with patch.object(ticket, "save"), patch.object(ticket, "update_order_status") as update_order:
			ticket.set_status("Cancelled")
		update_order.assert_not_called()

	def test_merge_rejects_different_brands_before_mutating_orders(self):
		target = frappe._dict(name="ORDER-1", store="STORE-1", cashier_session="SESSION-1",
			restaurant_brand="BRAND-A", order_type="Dine In", customer="CUSTOMER-1", external_reference=None)
		source = frappe._dict(name="ORDER-2", store="STORE-1", cashier_session="SESSION-1",
			restaurant_brand="BRAND-B", order_type="Dine In", customer="CUSTOMER-1", external_reference=None)
		with patch("rms.api.pos.get_owned_draft_order", side_effect=[target, source]):
			with self.assertRaisesRegex(frappe.ValidationError, "same restaurant brand"):
				merge_orders("ORDER-1", "ORDER-2")
		self.assertEqual(target.name, "ORDER-1")

	def test_split_must_leave_a_positive_line_on_the_source_order(self):
		source = SimpleNamespace(name="ORDER-1", items=[
			frappe._dict(name="ROW-1", qty=2, uom="Nos"),
			frappe._dict(name="ROW-2", qty=1, uom="Nos"),
		], order_type="Takeaway")
		with patch("rms.api.pos.get_owned_draft_order", return_value=source), \
				patch("frappe.db.get_value", return_value=0):
			with self.assertRaisesRegex(frappe.ValidationError, "At least one order line must remain"):
				split_order("ORDER-1", '{"ROW-1": 2, "ROW-2": 1}')

	def test_split_order_assigns_guest_labels_to_both_checks(self):
		source = frappe.new_doc("POS Order")
		source.name = "ORDER-1"
		source.store = "STORE-1"
		source.cashier_session = "SESSION-1"
		source.restaurant_brand = "BRAND-1"
		source.order_type = "Takeaway"
		source.customer = "CUSTOMER-1"
		source.dining_table = "TABLE-1"
		source.items = [frappe._dict(name="ROW-1", selling_product="PRODUCT-1", option_parent=None, qty=2,
			uom="Nos", notes=None, modifiers="[]")]
		source.save = unittest.mock.Mock()
		source.add_comment = unittest.mock.Mock()
		source.set = unittest.mock.Mock()
		split = frappe.new_doc("POS Order")
		split.insert = unittest.mock.Mock(return_value=split)
		split.add_comment = unittest.mock.Mock()
		split.append = unittest.mock.Mock()
		table = frappe._dict(store="STORE-1", dining_area="AREA-1", enabled=1)
		def get_value(doctype, *args, **kwargs):
			return table if doctype == "Dining Table" else 0
		with patch("rms.api.pos.get_owned_draft_order", return_value=source), \
				patch("rms.api.pos.frappe.new_doc", return_value=split), \
				patch("rms.api.pos.frappe.db.get_value", side_effect=get_value):
			result = split_order("ORDER-1", '{"ROW-1": 1}', "TABLE-1", " Mariam ", " Omar ")
		self.assertEqual(source.check_label, "Mariam")
		self.assertEqual(split.check_label, "Omar")
		self.assertEqual(split.table_check_group, source.table_check_group)
		self.assertEqual(result["name"], split.name)

	def test_table_transfer_flag_allows_only_the_locked_table_context_change(self):
		order = frappe.new_doc("POS Order")
		order.dining_area = "AREA-2"
		order.dining_table = "TABLE-2"
		previous = frappe.new_doc("POS Order")
		previous.dining_area = "AREA-1"
		previous.dining_table = "TABLE-1"
		order.flags.allow_table_transfer = True
		POSOrder.compare_locked_snapshot(order, previous)

		order.flags.allow_table_transfer = False
		with self.assertRaisesRegex(frappe.ValidationError, "context cannot change"):
			POSOrder.compare_locked_snapshot(order, previous)

