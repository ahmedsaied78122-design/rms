import unittest
from unittest.mock import patch

import frappe
from frappe.utils import getdate

from rms.rms.report.product_sales_summary.product_sales_summary import (
	execute,
	merge_product_rows,
)


class TestProductSalesSummary(unittest.TestCase):
	def test_cashier_cannot_read_product_sales_report(self):
		with patch("frappe.get_roles", return_value=["POS Cashier"]), \
				patch("frappe.session", frappe._dict(user="cashier@example.com")):
			with self.assertRaises(frappe.PermissionError):
				execute({"from_date": "2026-10-01", "to_date": "2026-10-02"})

	def test_product_sales_report_date_range_is_bounded(self):
		with patch("frappe.get_roles", return_value=["POS Manager"]), \
				patch("frappe.session", frappe._dict(user="manager@example.com")):
			with self.assertRaisesRegex(frappe.ValidationError, "90 days or less"):
				execute({"from_date": "2026-01-01", "to_date": "2026-04-01"})

	def test_store_assignment_and_filters_apply_to_both_queries(self):
		filters = {"from_date": "2026-10-01", "to_date": "2026-10-02", "store": "STORE-1",
			"restaurant_brand": "BRAND-1", "selling_product": "PRODUCT-1"}
		with patch("frappe.get_roles", return_value=["POS Manager"]), \
				patch("frappe.session", frappe._dict(user="manager@example.com")), \
				patch("frappe.db.sql", side_effect=[[], []]) as sql:
			columns, rows = execute(filters)
		self.assertEqual(sql.call_count, 2)
		for query, params in (call.args for call in sql.call_args_list):
			self.assertIn("scope_user.user = %(user)s", query)
			self.assertIn("o.store = %(store)s", query)
			self.assertIn("o.restaurant_brand = %(restaurant_brand)s", query)
			self.assertIn("product.name = %(selling_product)s", query)
			self.assertEqual(params["user"], "manager@example.com")
			if "tabPOS Return" in query:
				self.assertIn("TIME(ret.approved_at) < COALESCE(store.operating_day_end", query)
		self.assertTrue(columns)
		self.assertEqual(rows, [])

	def test_sales_and_returns_merge_by_product_and_subtract(self):
		key = (getdate("2026-10-02"), "STORE-1", "BRAND-1", "PRODUCT-1", "ITEM-1", "EGP")
		sales = [frappe._dict(business_date=key[0], store=key[1], restaurant_brand=key[2],
			selling_product=key[3], item_code=key[4], currency=key[5], product_title="Coffee",
			qty_sold=5, gross_sales=250)]
		returns = [frappe._dict(business_date=key[0], store=key[1], restaurant_brand=key[2],
			selling_product=key[3], item_code=key[4], currency=key[5], product_title="Coffee",
			qty_returned=1, returned_amount=50)]
		rows = merge_product_rows(sales, returns)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["net_qty"], 4)
		self.assertEqual(rows[0]["net_sales"], 200)

	def test_return_without_sales_on_approval_date_is_retained(self):
		row = frappe._dict(business_date=getdate("2026-10-02"), store="STORE-1", restaurant_brand="BRAND-1",
			selling_product="PRODUCT-1", item_code="ITEM-1", currency="EGP", product_title="Coffee",
			qty_returned=1, returned_amount=50)
		rows = merge_product_rows([], [row])
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["qty_sold"], 0)
		self.assertEqual(rows[0]["net_sales"], -50)
