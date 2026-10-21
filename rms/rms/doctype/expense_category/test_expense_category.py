import unittest
from unittest.mock import patch

import frappe

from rms.rms.doctype.expense_category.expense_category import ExpenseCategory


class TestExpenseCategory(unittest.TestCase):
	def make_category(self):
		category = frappe.new_doc("Expense Category")
		category.company = "COMPANY-1"
		category.expense_account = "EXPENSE-1"
		return category

	def test_expense_account_must_be_company_expense_ledger(self):
		category = self.make_category()
		with patch("frappe.db.get_value", return_value=frappe._dict(
				company="COMPANY-OTHER", root_type="Asset", is_group=0, account_currency="EGP")):
			with self.assertRaisesRegex(frappe.ValidationError, "non-group Expense Account"):
				ExpenseCategory.validate(category)

	def test_expense_account_must_use_company_currency(self):
		category = self.make_category()
		with patch("frappe.db.get_value", side_effect=[
				frappe._dict(company="COMPANY-1", root_type="Expense", is_group=0, account_currency="USD"),
				"EGP"]):
			with self.assertRaisesRegex(frappe.ValidationError, "Company currency"):
				ExpenseCategory.validate(category)
