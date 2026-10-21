import unittest
from unittest.mock import patch

import frappe

import rms.api.pos as pos_api
from rms.rms.doctype.pos_user.pos_user import POSUser


class TestPOSUser(unittest.TestCase):
	def test_role_summary_endpoint_returns_sorted_effective_roles_for_selected_user(self):
		with patch("rms.api.pos.frappe.has_permission", return_value=True), \
				patch("rms.api.pos.frappe.db.get_value", return_value="cashier@example.com"), \
				patch("rms.api.pos.frappe.get_roles", return_value=["POS Cashier", "Kitchen Operator", "POS Cashier"]):
			self.assertEqual(pos_api.get_pos_user_role_summary("cashier@example.com"), "Kitchen Operator, POS Cashier")

	def test_role_summary_endpoint_requires_pos_user_read_permission(self):
		with patch("rms.api.pos.frappe.has_permission", return_value=False):
			with self.assertRaisesRegex(frappe.PermissionError, "POS User"):
				pos_api.get_pos_user_role_summary("cashier@example.com")

	def test_role_summary_endpoint_rejects_disabled_frappe_user(self):
		with patch("rms.api.pos.frappe.has_permission", return_value=True), patch("rms.api.pos.frappe.db.get_value", return_value=None):
			with self.assertRaisesRegex(frappe.ValidationError, "enabled Frappe User"):
				pos_api.get_pos_user_role_summary("disabled@example.com")

	def test_pos_user_form_has_user_facing_operational_permissions(self):
		fields = {field.fieldname for field in frappe.get_meta("POS User").fields}
		self.assertTrue({
			"can_view_tables", "can_view_open_orders", "can_view_sales_history", "can_reprint_receipts",
			"can_checkout", "can_edit_open_orders", "can_apply_manual_discount", "can_cancel_orders", "can_transfer_tables",
			"can_split_orders", "can_merge_orders", "can_request_returns", "can_payout", "can_access_kitchen",
			"can_prepare_orders", "can_pick_orders", "can_acknowledge_cancellations", "allowed_brands",
			"allowed_order_types", "allowed_preparation_areas", "discount_approval_password",
		} <= fields)
		meta = frappe.get_meta("POS User")
		self.assertEqual(meta.get_field("discount_approval_password").fieldtype, "Password")
		for fieldname in ("can_access_kitchen", "can_prepare_orders", "can_pick_orders", "can_acknowledge_cancellations"):
			with self.subTest(fieldname=fieldname):
				self.assertIn("Kitchen Operator", meta.get_field(fieldname).description or "")

	def make_pos_user(self):
		user = frappe.new_doc("POS User")
		user.user = "cashier@example.com"
		user.append("stores", {"store": "STORE-1"})
		return user

	def test_pos_user_requires_enabled_frappe_user(self):
		user = self.make_pos_user()
		with patch("frappe.db.get_value", return_value=None):
			with self.assertRaisesRegex(frappe.ValidationError, "enabled Frappe User"):
				POSUser.validate_user(user)

	def test_pos_user_cannot_duplicate_frappe_user(self):
		user = self.make_pos_user()
		with patch("frappe.db.get_value", return_value="cashier@example.com"), \
				patch("frappe.db.exists", return_value="POS-USER-2"):
			with self.assertRaisesRegex(frappe.ValidationError, "already exists"):
				POSUser.validate_user(user)

	def test_pos_user_requires_enabled_store_assignment(self):
		user = self.make_pos_user()
		with patch("frappe.db.get_value", return_value=None):
			with self.assertRaisesRegex(frappe.ValidationError, "enabled Stores"):
				POSUser.validate_stores(user)

	def test_pos_user_allows_only_one_default_store(self):
		user = self.make_pos_user()
		user.stores[0].default_store = 1
		user.append("stores", {"store": "STORE-2", "default_store": 1})
		with patch("frappe.db.get_value", return_value="STORE-1"):
			with self.assertRaisesRegex(frappe.ValidationError, "Only one Store can be the default"):
				POSUser.validate_stores(user)

	def test_pos_user_rejects_employee_linked_to_another_user(self):
		user = self.make_pos_user()
		user.employee = "EMP-1"
		with patch("frappe.db.get_value", return_value=frappe._dict(status="Active", user_id="other@example.com")):
			with self.assertRaisesRegex(frappe.ValidationError, "different Frappe User"):
				POSUser.validate_employee(user)

	def test_pos_user_exposes_effective_roles_and_rejects_discount_limits_over_100(self):
		user = self.make_pos_user()
		user.max_manual_discount_percent = 101
		with patch("frappe.get_roles", return_value=["POS Cashier"]):
			with self.assertRaisesRegex(frappe.ValidationError, "between 0% and 100%"):
				POSUser.validate_permissions(user)

	def test_pos_user_displays_roles_from_the_linked_frappe_user(self):
		user = self.make_pos_user()
		user.max_manual_discount_percent = 10
		with patch("frappe.get_roles", return_value=["POS Cashier", "Kitchen Operator"]):
			POSUser.validate_permissions(user)
		self.assertEqual(user.roles_summary, "Kitchen Operator, POS Cashier")

	def test_pos_user_scope_rejects_duplicate_entries(self):
		user = self.make_pos_user()
		user.allowed_brands = [frappe._dict(restaurant_brand="BRAND-1"), frappe._dict(restaurant_brand="BRAND-1")]
		with self.assertRaisesRegex(frappe.ValidationError, "only be selected once"):
			POSUser.validate_scope_table(user, "allowed_brands", "restaurant_brand", "Restaurant Brand",
				"Store Brand Assignment", "restaurant_brand", {"STORE-1"})

	def test_pos_user_scope_rejects_records_outside_assigned_stores(self):
		user = self.make_pos_user()
		user.allowed_brands = [frappe._dict(restaurant_brand="BRAND-2")]
		with patch("frappe.get_all", return_value=["BRAND-1"]), patch("frappe.db.get_value", return_value="BRAND-2"):
			with self.assertRaisesRegex(frappe.ValidationError, "at least one assigned Store"):
				POSUser.validate_scope_table(user, "allowed_brands", "restaurant_brand", "Restaurant Brand",
					"Store Brand Assignment", "restaurant_brand", {"STORE-1"})
