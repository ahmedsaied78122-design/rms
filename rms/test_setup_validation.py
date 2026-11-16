"""Setup contracts checked without creating users, stock or accounting records."""
import unittest
from unittest.mock import patch

import frappe
from rms.rms.doctype.store.store import Store
from rms.rms.doctype.store_menu.store_menu import StoreMenu
from rms.rms.doctype.restaurant_brand.restaurant_brand import RestaurantBrand
from rms.rms.doctype.dining_area.dining_area import DiningArea
from rms.rms.doctype.dining_table.dining_table import DiningTable
from rms.rms.doctype.preparation_area.preparation_area import PreparationArea
from rms.rms.doctype.print_device.print_device import PrintDevice
from rms.rms.doctype.order_type.order_type import OrderType
from rms.rms.doctype.pos_action_reason.pos_action_reason import validate_pos_action_reason


class TestSetupValidation(unittest.TestCase):
	def doc(self, doctype, **values):
		return frappe.get_doc(dict(doctype=doctype, **values))

	def test_store_requires_exactly_one_default_brand(self):
		for flags in ([], [0], [1, 1]):
			store = self.doc("Store", brands=[dict(restaurant_brand=f"B{i}", is_default=f) for i, f in enumerate(flags)])
			with self.assertRaisesRegex(frappe.ValidationError, "exactly one"):
				store.validate_brands()

	def test_store_rejects_duplicate_or_disabled_brands(self):
		store = self.doc("Store", brands=[dict(restaurant_brand="B", is_default=1), dict(restaurant_brand="B")])
		with self.assertRaisesRegex(frappe.ValidationError, "only be added once"):
			store.validate_brands()
		store.set("brands", [dict(restaurant_brand="B", is_default=1)])
		with patch("frappe.db.get_value", return_value=0):
			with self.assertRaisesRegex(frappe.ValidationError, "disabled"):
				store.validate_brands()

	def test_store_warehouse_requires_same_company_enabled_leaf(self):
		store = self.doc("Store", company="C1", default_warehouse="W")
		for company, group, disabled in (("C2", 0, 0), ("C1", 1, 0), ("C1", 0, 1)):
			with patch("frappe.db.get_value", return_value=frappe._dict(company=company, is_group=group, disabled=disabled)):
				with self.assertRaisesRegex(frappe.ValidationError, "leaf Warehouse"):
					store.validate_defaults()
		with patch("frappe.db.get_value", return_value=frappe._dict(company="C1", is_group=0, disabled=0)):
			store.validate_defaults()

	def test_store_preparation_area_cannot_point_at_another_store(self):
		store = self.doc("Store", name="S1", default_preparation_area="A")
		with patch("frappe.db.get_value", return_value=frappe._dict(store="S2", enabled=1)):
			with self.assertRaisesRegex(frappe.ValidationError, "belong to this Store"):
				store.validate_defaults()

	def test_store_tax_template_must_belong_to_store_company(self):
		store = self.doc("Store", company="C1", order_type_taxes=[dict(order_type="OT", sales_taxes_and_charges_template="T")])
		with patch("frappe.db.get_value", side_effect=lambda dt, *a, **k: 1 if dt == "Order Type" else "C2"):
			with self.assertRaisesRegex(frappe.ValidationError, "Store Company"):
				store.validate_order_type_taxes()

	def test_store_rejects_duplicate_order_type_tax_assignments(self):
		store = self.doc("Store", order_type_taxes=[dict(order_type="OT"), dict(order_type="OT")])
		with patch("frappe.db.get_value", return_value=1):
			with self.assertRaisesRegex(frappe.ValidationError, "only one tax template"):
				store.validate_order_type_taxes()

	def test_menu_rejects_disabled_brand_and_duplicate_categories(self):
		menu = self.doc("Store Menu", restaurant_brand="B", categories=[dict(product_category="C"), dict(product_category="C")])
		with patch("frappe.db.get_value", return_value=0):
			with self.assertRaisesRegex(frappe.ValidationError, "enabled Brand"):
				menu.validate()
		with patch("frappe.db.get_value", return_value=1):
			with self.assertRaisesRegex(frappe.ValidationError, "only appear once"):
				menu.validate()

	def test_brand_menu_requires_matching_brand_and_enabled_menu(self):
		brand = self.doc("Restaurant Brand", name="B", menus=[dict(store_menu="M")])
		for result in (("OTHER", 1), ("B", 0)):
			with patch("frappe.db.get_value", return_value=result):
				with self.assertRaisesRegex(frappe.ValidationError, "belong to this Brand"):
					brand.validate()
		with patch("frappe.db.get_value", return_value=("B", 1)):
			brand.validate()

	def test_dining_area_requires_assigned_brand(self):
		area = self.doc("Dining Area", store="S", restaurant_brand="B")
		with patch("frappe.db.get_value", return_value=1), patch("frappe.db.exists", return_value=False):
			with self.assertRaisesRegex(frappe.ValidationError, "assigned to this Store"):
				area.validate()

	def test_dining_table_requires_matching_area_and_positive_capacity(self):
		table = self.doc("Dining Table", store="S", dining_area="A", capacity=4)
		with patch("frappe.db.get_value", return_value="OTHER"):
			with self.assertRaisesRegex(frappe.ValidationError, "selected Store"):
				table.validate()
		table.capacity = 0
		with patch("frappe.db.get_value", return_value="S"):
			with self.assertRaisesRegex(frappe.ValidationError, "at least one"):
				table.validate()

	def test_preparation_requires_enabled_printer_and_clears_unused_link(self):
		area = self.doc("Preparation Area", has_printer=1)
		with self.assertRaisesRegex(frappe.ValidationError, "Print Device"):
			area.validate()
		area.print_device = "PRINTER"
		with patch("frappe.db.get_value", return_value=0):
			with self.assertRaisesRegex(frappe.ValidationError, "disabled"):
				area.validate()
		area.has_printer = 0
		area.validate()
		self.assertIsNone(area.print_device)

	def test_each_print_method_requires_only_its_connection_fields(self):
		for method, field, value in (("Network Socket", "host", "127.0.0.1"), ("IPP", "ipp_url", "ipp://printer.local/jobs"), ("System Queue", "queue_name", "QUEUE")):
			device = self.doc("Print Device", print_method=method, port=9100)
			with self.assertRaises(frappe.ValidationError):
				device.validate()
			device.set(field, value)
			device.validate()

	def test_print_connection_port_has_valid_bounds(self):
		for port in (-1, 65536):
			device = self.doc("Print Device", print_method="Network Socket", host="127.0.0.1", port=port)
			with self.assertRaisesRegex(frappe.ValidationError, "65535"):
				device.validate()

	def test_order_type_account_must_be_matching_company_leaf_and_root(self):
		order_type = self.doc("Order Type")
		for account in (dict(company="C2", root_type="Income", is_group=0), dict(company="C1", root_type="Income", is_group=1), dict(company="C1", root_type="Expense", is_group=0)):
			with patch("frappe.db.get_value", return_value=frappe._dict(account)):
				with self.assertRaises(frappe.ValidationError):
					order_type.validate_account("C1", "ACCOUNT", "Income")

	def test_reason_is_checked_for_enabled_and_action_scope(self):
		for enabled, scope in ((0, "Both"), (1, "Void")):
			with patch("frappe.get_doc", return_value=frappe._dict(enabled=enabled, applies_to=scope, reason="Reason")):
				with self.assertRaises(frappe.ValidationError):
					validate_pos_action_reason("R", "Return")
		with patch("frappe.get_doc", return_value=frappe._dict(enabled=1, applies_to="Both", reason="Reason")):
			self.assertEqual(validate_pos_action_reason("R", "Return"), "Reason")

	def test_dining_table_rejects_a_disabled_area_in_the_same_store(self):
		table = self.doc("Dining Table", store="S", dining_area="A", capacity=4)
		with patch("frappe.db.get_value", side_effect=["S", 0]):
			with self.assertRaisesRegex(frappe.ValidationError, "enabled"):
				table.validate()

	def test_kitchen_ticket_rejects_zero_or_negative_line_quantities(self):
		from rms.rms.doctype.kitchen_ticket.kitchen_ticket import KitchenTicket
		for qty in (0, -1):
			ticket = self.doc("Kitchen Ticket", pos_order="O", items=[dict(pos_order_item="LINE", selling_product="P", qty=qty)])
			with patch("frappe.get_all", return_value=["LINE"]):
				with self.assertRaisesRegex(frappe.ValidationError, "greater than zero"):
					ticket.validate_items()
