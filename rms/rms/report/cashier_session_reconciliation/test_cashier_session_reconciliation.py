import unittest
from unittest.mock import patch

import frappe

from rms.rms.report.cashier_session_reconciliation.cashier_session_reconciliation import execute


class TestCashierSessionReconciliation(unittest.TestCase):
	def test_cashier_cannot_read_reconciliation_report(self):
		with patch("frappe.get_roles", return_value=["POS Cashier"]), \
				patch("frappe.session", frappe._dict(user="cashier@example.com")):
			with self.assertRaises(frappe.PermissionError):
				execute({"from_date": "2026-10-01", "to_date": "2026-10-02"})

	def test_date_range_is_bounded(self):
		with patch("frappe.get_roles", return_value=["POS Manager"]), \
				patch("frappe.session", frappe._dict(user="manager@example.com")):
			with self.assertRaisesRegex(frappe.ValidationError, "90 days or less"):
				execute({"from_date": "2026-01-01", "to_date": "2026-04-01"})

	def test_store_scope_is_enforced_in_the_query(self):
		filters = {"from_date": "2026-10-01", "to_date": "2026-10-02", "store": "STORE-1"}
		with patch("frappe.get_roles", return_value=["POS Manager"]), \
				patch("frappe.session", frappe._dict(user="manager@example.com")), \
				patch("frappe.get_doc"), patch("frappe.db.sql", return_value=[]) as sql:
			columns, rows = execute(filters)
		query, params = sql.call_args.args
		self.assertIn("scope_user.user = %(user)s", query)
		self.assertEqual(params["store"], "STORE-1")
		self.assertEqual(params["user"], "manager@example.com")
		self.assertTrue(columns)
		self.assertEqual(rows, [])
