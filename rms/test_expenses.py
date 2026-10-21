import unittest
from unittest.mock import Mock, patch

import frappe
import rms.expenses as expenses

from rms.expenses import (
	_get_expense_payment_account,
	create_shift_expense,
	issue_shift_expense_approval_code,
	redeem_shift_expense_approval_code,
)
from rms.api.pos import get_shift_expense_permission_query
from rms.rms.doctype.shift_expense.shift_expense import ShiftExpense


class TestPOSExpenses(unittest.TestCase):
	def test_pos_manager_expense_list_is_limited_to_assigned_pos_user_stores(self):
		with patch("frappe.get_roles", return_value=["POS Manager"]), \
				patch("frappe.db.get_value", return_value="POS-USER-1"), \
				patch("frappe.db.escape", return_value="'manager@example.com'"):
			condition = get_shift_expense_permission_query("manager@example.com")
		self.assertIn("`tabShift Expense`.store in", condition)
		self.assertIn("`tabPOS User Store`", condition)
		self.assertIn("manager@example.com", condition)

	def test_cashier_expense_list_is_limited_to_their_own_records(self):
		with patch("frappe.get_roles", return_value=["POS Cashier"]), \
				patch("frappe.db.escape", return_value="'cashier@example.com'"):
			condition = get_shift_expense_permission_query("cashier@example.com")
		self.assertEqual(condition, "`tabShift Expense`.owner = 'cashier@example.com'")

	def test_pos_manager_can_list_only_accessible_pending_expenses_with_staff_names(self):
		reader = getattr(expenses, "get_manager_pending_shift_expenses", None)
		self.assertTrue(callable(reader), "POS manager expense review is not available in POS")
		rows = [frappe._dict(name="RMS-EXP-1", store="STORE-1", cashier="cashier@example.com",
			expense_category="Staff Meals", amount=75, currency="EGP", mode_of_payment="Cash")]
		with patch("frappe.get_roles", return_value=["POS Manager"]), \
				patch("frappe.session", frappe._dict(user="manager@example.com")), \
				patch("frappe.get_list", return_value=rows) as get_list, \
				patch("frappe.get_all", return_value=[frappe._dict(name="cashier@example.com", full_name="Mariam El-Sayed")]):
			result = reader()
		self.assertEqual(result[0].cashier_full_name, "Mariam El-Sayed")
		self.assertNotIn("cashier", result[0])
		self.assertEqual(get_list.call_args.args[0], "Shift Expense")
		self.assertEqual(get_list.call_args.kwargs["filters"], {
			"status": "Pending Approval", "owner": ["!=", "manager@example.com"],
		})

	def test_cashier_cannot_open_manager_expense_review(self):
		reader = getattr(expenses, "get_manager_pending_shift_expenses", None)
		self.assertTrue(callable(reader), "POS manager expense review is not available in POS")
		with patch("frappe.get_roles", return_value=["POS Cashier"]), \
				patch("frappe.session", frappe._dict(user="cashier@example.com")):
			with self.assertRaises(frappe.PermissionError):
				reader()

	def test_approval_posts_standard_balanced_journal_entry_and_refreshes_session(self):
		expense = frappe.new_doc("Shift Expense")
		expense.name = "RMS-EXP-1"
		expense.status = "Pending Approval"
		expense.company = "COMPANY-1"
		expense.business_date = "2026-10-19"
		expense.expense_category = "Staff Meals"
		expense.expense_account = "Staff Meals - RMS"
		expense.cost_center = "Main - RMS"
		expense.payment_account = "Cash - RMS"
		expense.amount = 75
		expense.remarks = "Staff meal"
		expense.cashier_session = "SESSION-1"
		journal = frappe._dict(name="JE-1", docstatus=0, accounts=[], flags=frappe._dict())
		journal.append = lambda field, row: journal[field].append(frappe._dict(row))
		journal.insert = Mock(side_effect=lambda ignore_permissions: setattr(journal, "name", "JE-1"))
		journal.submit = Mock(side_effect=lambda: setattr(journal, "docstatus", 1))
		session = frappe._dict(status="Open", reload=Mock(), save=Mock())
		with patch("frappe.new_doc", return_value=journal), \
				patch("frappe.get_doc", side_effect=[journal, session]), \
				patch("rms.rms.doctype.shift_expense.shift_expense.frappe.utils.now_datetime", return_value="2026-10-20 12:00:00"), \
				patch("frappe.db.commit"), patch.object(expense, "save"):
			journal_name = ShiftExpense.post_to_ledger(expense, "manager@example.com")
		self.assertEqual(journal_name, "JE-1")
		self.assertEqual(journal.accounts[0].debit_in_account_currency, 75)
		self.assertEqual(journal.accounts[0].cost_center, "Main - RMS")
		self.assertEqual(journal.accounts[1].credit_in_account_currency, 75)
		self.assertEqual(journal.accounts[1].account, "Cash - RMS")
		journal.submit.assert_called_once_with()
		session.save.assert_called_once_with(ignore_permissions=True)
		self.assertEqual(expense.status, "Posted")

	def test_payment_account_must_be_company_cash_or_bank_account(self):
		with patch("frappe.db.get_value", side_effect=["CASH-1", frappe._dict(
				company="COMPANY-1", root_type="Expense", account_type="Expense Account", is_group=0,
				account_currency="EGP"), "EGP"]):
			with self.assertRaisesRegex(frappe.ValidationError, "Cash or Bank account"):
				_get_expense_payment_account("COMPANY-1", "Cash")

	def test_cashier_without_payout_permission_creates_pending_expense(self):
		session = frappe._dict(name="SESSION-1", store="STORE-1", user="cashier@example.com",
			status="Open", business_date="2026-10-19", payments=[frappe._dict(mode_of_payment="Cash")])
		category = frappe._dict(enabled=1, company="COMPANY-1", expense_account="EXPENSE-1", cost_center="CC-1")
		doc = frappe._dict(name="RMS-EXP-1", status="Pending Approval", journal_entry=None,
			flags=frappe._dict(from_pos_api=False), insert=Mock())
		with patch("rms.expenses._get_open_expense_session", return_value=session), \
				patch("rms.expenses.flt", return_value=75.0) as normalize_amount, \
				patch("frappe.get_precision", return_value=2), \
				patch("frappe.db.get_value", side_effect=[category, "COMPANY-1",
					frappe._dict(company="COMPANY-1", root_type="Expense", is_group=0, account_currency="EGP"), "EGP",
					frappe._dict(company="COMPANY-1", is_group=0)]), \
				patch("rms.expenses._get_expense_payment_account", return_value="CASH-1"), \
				patch("rms.expenses._can_post_expense_directly", return_value=False), \
				patch("frappe.new_doc", return_value=doc):
			result = create_shift_expense("Meals", 75, "Cash", "Staff meal")
		self.assertEqual(result["status"], "Pending Approval")
		self.assertTrue(result["requires_approval"])
		normalize_amount.assert_called_once_with(75, precision=2)
		doc.insert.assert_called_once_with(ignore_permissions=True)
		self.assertEqual(doc.cashier_session, "SESSION-1")
		self.assertEqual(doc.payment_account, "CASH-1")
		self.assertEqual(doc.expense_account, "EXPENSE-1")

	def test_manager_issues_hashed_code_scoped_to_one_expense(self):
		expense = frappe._dict(name="RMS-EXP-1", owner="cashier@example.com", store="STORE-1", status="Pending Approval")
		challenge = frappe._dict(name="RMS-APR-1", flags=frappe._dict(), update=Mock(), insert=Mock(), expires_at="2026-10-19 12:03:00")
		challenge.insert.side_effect = lambda **kwargs: setattr(challenge, "name", "RMS-APR-1")
		with patch("frappe.get_roles", return_value=["POS Manager"]), \
				patch("frappe.session", frappe._dict(user="manager@example.com")), \
				patch("frappe.get_doc", return_value=expense), \
				patch("rms.expenses.assert_store_access"), \
				patch("frappe.get_all", return_value=[]), \
				patch("frappe.new_doc", return_value=challenge):
			result = issue_shift_expense_approval_code("RMS-EXP-1")
		self.assertEqual(result["challenge"], "RMS-APR-1")
		self.assertEqual(len(result["code"]), 6)
		self.assertNotEqual(challenge.code_hash, result["code"])
		self.assertEqual(challenge.subject_name, "RMS-EXP-1")
		self.assertEqual(challenge.action, "Post Shift Expense")

	def test_redeeming_code_posts_only_the_challenge_expense(self):
		session = frappe._dict(name="SESSION-1", status="Open")
		expense = frappe._dict(name="RMS-EXP-1", owner="cashier@example.com", cashier_session="SESSION-1",
			status="Pending Approval")
		expense.post_to_ledger = Mock(side_effect=lambda user: setattr(expense, "status", "Posted"))
		challenge = frappe._dict(approver="manager@example.com", verify_code=Mock())
		with patch("rms.expenses._get_open_expense_session", return_value=session), \
				patch("frappe.session", frappe._dict(user="cashier@example.com")), \
				patch("frappe.get_doc", side_effect=[expense, challenge]), \
				patch("frappe.get_all", return_value=[frappe._dict(name="RMS-APR-1")]), \
				patch("frappe.db.sql"):
			result = redeem_shift_expense_approval_code("RMS-EXP-1", "381604")
		self.assertEqual(result["status"], "Posted")
		challenge.verify_code.assert_called_once_with("381604")
		expense.post_to_ledger.assert_called_once_with("manager@example.com")
