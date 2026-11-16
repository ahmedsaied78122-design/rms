import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from rms.api.pos import get_catalog


class TestPOSCatalogSnapshot(unittest.TestCase):
	def setUp(self):
		stack = ExitStack()
		self.addCleanup(stack.close)
		stack.enter_context(patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True))
		self.rows = [frappe._dict(name=f"Product {i}", title=f"Product {i}",
			product_category="Food", image=None, item=f"Item {i}", selling_price=10,
			uom=None, sequence_id=i, has_options=0, is_modifier=0, can_be_sold_separately=1)
			for i in range(251)]
		self.role = stack.enter_context(patch("rms.api.pos.require_pos_role"))
		self.access = stack.enter_context(patch("rms.api.pos.assert_store_access"))
		stack.enter_context(patch("rms.api.pos.get_brands", return_value=[{"name": "East"}]))
		stack.enter_context(patch("rms.api.pos.get_order_types", return_value=[{"name": "Takeaway"}, {"name": "Delivery"}]))
		stack.enter_context(patch("rms.api.pos.get_menu_category_ids", return_value=["Food"]))
		self.get_all = stack.enter_context(patch("rms.api.pos.frappe.get_all", side_effect=self.read_rows))
		stack.enter_context(patch("rms.api.pos.frappe.get_doc", side_effect=self.product_doc))
		stack.enter_context(patch("rms.api.pos._", side_effect=lambda message: message))
		stack.enter_context(patch("rms.api.pos.frappe.throw", side_effect=frappe.PermissionError))

	def read_rows(self, doctype, **kwargs):
		if doctype == "Selling Product" and not kwargs.get("pluck"):
			limit = kwargs.get("limit_page_length")
			return self.rows[:limit] if limit else self.rows
		if doctype == "Product Category":
			return [frappe._dict(name="Food", title="Food")]
		return []

	def product_doc(self, payload):
		return SimpleNamespace(**payload, resolve_price=lambda store, order_type, brand, strict=False: {
			"selling_price": 25 if order_type == "Takeaway" else 32, "price_list": "Standard Selling"})

	def test_snapshot_includes_products_after_200_with_current_context_prices(self):
		for order_type, price in (("Takeaway", 25), ("Delivery", 32)):
			rows = get_catalog("Maadi", "East", order_type, full_menu=1)
			self.assertEqual(len(rows), 251)
			self.assertEqual(rows[-1]["name"], "Product 250")
			self.assertTrue(all(row["price"] == price for row in rows))
			self.assertTrue(all("item" not in row for row in rows))
		self.role.assert_called()
		self.access.assert_called_with("Maadi")

	def test_existing_bounded_catalog_keeps_its_200_limit(self):
		self.assertEqual(len(get_catalog("Maadi", "East", "Takeaway", limit=1000)), 200)

	def test_snapshot_keeps_store_brand_and_order_type_access_checks(self):
		self.access.side_effect = frappe.PermissionError
		with self.assertRaises(frappe.PermissionError):
			get_catalog("Other", "East", "Takeaway", full_menu=1)
		self.get_all.assert_not_called()
		self.access.side_effect = None
		for brand, order_type in (("Other", "Takeaway"), ("East", "Other")):
			with self.assertRaises(frappe.PermissionError):
				get_catalog("Maadi", brand, order_type, full_menu=1)
		self.get_all.assert_not_called()


if __name__ == "__main__":
	unittest.main()
