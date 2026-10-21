import unittest
from unittest.mock import patch

import frappe
from frappe.utils import getdate

from rms.rms.report.pos_sales_summary.pos_sales_summary import execute, merge_sales_and_returns


class TestPOSSalesSummary(unittest.TestCase):
	def test_cashier_cannot_read_sales_report(self):
		with patch("frappe.get_roles", return_value=["POS Cashier"]), \
				patch("frappe.session", frappe._dict(user="cashier@example.com")):
			with self.assertRaises(frappe.PermissionError):
				execute({"from_date": "2026-10-01", "to_date": "2026-10-02"})

	def test_sales_report_date_range_is_bounded(self):
		with patch("frappe.get_roles", return_value=["POS Manager"]), \
				patch("frappe.session", frappe._dict(user="manager@example.com")):
			with self.assertRaisesRegex(frappe.ValidationError, "90 days or less"):
				execute({"from_date": "2026-01-01", "to_date": "2026-04-01"})

	def test_store_scope_and_filters_apply_to_sales_and_returns_queries(self):
		filters = {"from_date": "2026-10-01", "to_date": "2026-10-02", "store": "STORE-1", "order_type": "Dine In"}
		with patch("frappe.get_roles", return_value=["POS Manager"]), \
				patch("frappe.session", frappe._dict(user="manager@example.com")), \
				patch("frappe.db.sql", side_effect=[[], []]) as sql:
			columns, rows = execute(filters)
		self.assertEqual(sql.call_count, 2)
		for query, params in (call.args for call in sql.call_args_list):
			self.assertIn("scope_user.user = %(user)s", query)
			self.assertIn("AND o.store = %(store)s", query)
			self.assertIn("o.order_type = %(order_type)s", query)
			self.assertEqual(params["user"], "manager@example.com")
			if "tabPOS Return" in query:
				self.assertIn("TIME(ret.approved_at) < COALESCE(store.operating_day_end", query)
		self.assertTrue(columns)
		self.assertEqual(rows, [])

	def test_return_totals_are_merged_on_approval_business_date_and_subtracted(self):
		key = (getdate("2026-10-02"), "STORE-1", "BRAND-1", "Dine In", "EGP")
		sales = [frappe._dict(business_date=key[0], store=key[1], restaurant_brand=key[2], order_type=key[3],
			currency=key[4], paid_orders=3, qty_sold=7, subtotal=200, tax_total=24, gross_sales=224)]
		returns = [frappe._dict(business_date=key[0], store=key[1], restaurant_brand=key[2], order_type=key[3],
			currency=key[4], approved_returns=20)]
		rows = merge_sales_and_returns(sales, returns)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["paid_orders"], 3)
		self.assertEqual(rows[0]["approved_returns"], 20)
		self.assertEqual(rows[0]["net_sales"], 204)

