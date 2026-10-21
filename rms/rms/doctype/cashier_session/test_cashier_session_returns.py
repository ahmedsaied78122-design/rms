import unittest
from unittest.mock import patch

import frappe

from rms.rms.doctype.cashier_session.cashier_session import CashierSession
from rms.rms.doctype.pos_return.pos_return import POSReturn


class TestCashierSessionReturns(unittest.TestCase):
	def test_session_close_transitions_save_with_internal_permissions(self):
		session = frappe.new_doc("Cashier Session")
		session.name = "SESSION-1"
		session.status = "Open"
		with patch("frappe.db.sql"), patch.object(session, "reload"), \
				patch("frappe.db.exists", return_value=False), patch.object(session, "save") as save:
			session.begin_closing()
		save.assert_called_once_with(ignore_permissions=True)

	def test_successful_close_records_closed_at(self):
		session = frappe.new_doc("Cashier Session")
		session.name = "SESSION-1"
		session.status = "Closed"
		session.pos_opening_entry = "OPEN-1"
		session.pos_closing_entry = "CLOSE-1"
		session.append("payments", {"mode_of_payment": "Cash", "actual_amount": 100})
		closed_at = "2026-10-20 12:00:00"
		with patch.object(session, "get_doc_before_save", return_value=frappe._dict(status="Closing")), \
				patch("frappe.db.get_value", side_effect=["Closed", "Submitted"]), \
				patch("frappe.db.exists", return_value=False), \
				patch("rms.rms.doctype.cashier_session.cashier_session.now_datetime", return_value=closed_at):
			session.validate_status_change()
		self.assertEqual(session.closed_at, closed_at)

	def test_pending_expense_blocks_closing_but_not_an_open_session_save(self):
		session = frappe.new_doc("Cashier Session")
		session.name = "SESSION-1"
		session.status = "Open"
		with patch.object(session, "get_doc_before_save", return_value=frappe._dict(status="Open")), \
				patch("frappe.db.exists", side_effect=lambda doctype, filters: doctype == "Shift Expense"):
			session.validate_status_change()

	def test_closed_session_keeps_actual_cash_count(self):
		session = frappe.new_doc("Cashier Session")
		session.name = "SESSION-1"
		session.status = "Closed"
		session.append("payments", {"mode_of_payment": "Cash", "actual_amount": 500})
		with patch("frappe.get_all", return_value=[frappe._dict(mode_of_payment="Cash")]):
			session.validate_payments()

	def test_open_session_accepts_zero_as_unentered_currency_count(self):
		session = frappe.new_doc("Cashier Session")
		session.name = "SESSION-1"
		session.status = "Open"
		session.append("payments", {"mode_of_payment": "Cash", "opening_amount": 500, "actual_amount": 0})
		with patch("frappe.get_all", return_value=[frappe._dict(mode_of_payment="Cash")]):
			session.validate_payments()

	def test_open_session_rejects_nonzero_actual_count(self):
		session = frappe.new_doc("Cashier Session")
		session.status = "Open"
		session.append("payments", {"mode_of_payment": "Cash", "actual_amount": 500})
		with patch("frappe.get_all", return_value=[frappe._dict(mode_of_payment="Cash")]):
			with self.assertRaisesRegex(frappe.ValidationError, "only be entered while closing"):
				session.validate_payments()

	def test_open_session_does_not_show_a_cash_difference_before_count(self):
		session = frappe.new_doc("Cashier Session")
		session.name = "SESSION-1"
		session.status = "Open"
		session.append("payments", {"mode_of_payment": "Cash", "opening_amount": 500, "actual_amount": 0})

		def get_all(doctype, **kwargs):
			if doctype in ("POS Order", "POS Return"):
				return []
			if doctype in ("POS Order Payment", "POS Return Payment", "Shift Expense"):
				return []
			self.fail(f"Unexpected query: {doctype}")

		with patch("frappe.get_all", side_effect=get_all):
			session.update_expected_amounts()

		self.assertEqual(session.payments[0].expected_amount, 500)
		self.assertEqual(session.payments[0].difference, 0)

	def test_approved_refunds_reduce_expected_amount_by_payment_method(self):
		session = frappe.new_doc("Cashier Session")
		session.name = "SESSION-1"
		session.status = "Closed"
		session.append("payments", {"mode_of_payment": "Cash", "opening_amount": 20, "actual_amount": 55})
		session.append("payments", {"mode_of_payment": "Card", "opening_amount": 0, "actual_amount": 55})

		def get_all(doctype, **kwargs):
			if doctype == "POS Order":
				return ["ORDER-1"]
			if doctype == "POS Order Payment":
				return [frappe._dict(mode_of_payment="Cash", amount=40), frappe._dict(mode_of_payment="Card", amount=60)]
			if doctype == "POS Return":
				self.assertEqual(kwargs["filters"]["status"], "Approved")
				return ["RETURN-1"]
			if doctype == "POS Return Payment":
				return [frappe._dict(mode_of_payment="Cash", amount=10), frappe._dict(mode_of_payment="Card", amount=5)]
			if doctype == "Shift Expense":
				return []
			self.fail(f"Unexpected query: {doctype}")

		with patch("frappe.get_all", side_effect=get_all):
			CashierSession.update_expected_amounts(session)

		self.assertEqual(session.payments[0].expected_amount, 50)
		self.assertEqual(session.payments[0].difference, 5)
		self.assertEqual(session.payments[1].expected_amount, 55)
		self.assertEqual(session.payments[1].difference, 0)

	def test_posted_shift_expenses_reduce_expected_by_payment_method(self):
		session = frappe.new_doc("Cashier Session")
		session.name = "SESSION-1"
		session.append("payments", {"mode_of_payment": "Cash", "opening_amount": 20})
		session.append("payments", {"mode_of_payment": "Card", "opening_amount": 0})

		def get_all(doctype, **kwargs):
			if doctype == "POS Order":
				return ["ORDER-1"]
			if doctype == "POS Order Payment":
				return [frappe._dict(mode_of_payment="Cash", amount=80), frappe._dict(mode_of_payment="Card", amount=40)]
			if doctype == "POS Return":
				return []
			if doctype == "POS Return Payment":
				return []
			if doctype == "Shift Expense":
				return [frappe._dict(mode_of_payment="Cash", amount=15), frappe._dict(mode_of_payment="Card", amount=10)]
			self.fail(f"Unexpected query: {doctype}")

		with patch("frappe.get_all", side_effect=get_all):
			CashierSession.update_expected_amounts(session)

		self.assertEqual(session.payments[0].expected_amount, 85)
		self.assertEqual(session.payments[1].expected_amount, 30)

	def test_pending_return_blocks_session_close(self):
		session = frappe.new_doc("Cashier Session")
		session.name = "SESSION-1"
		session.status = "Open"

		def exists(doctype, filters):
			return doctype == "POS Return"

		with patch("frappe.db.sql"), patch.object(session, "reload"), patch("frappe.db.exists", side_effect=exists):
			with self.assertRaisesRegex(frappe.ValidationError, "Approve or reject every pending POS Return"):
				session.begin_closing()

	def test_pending_shift_expense_blocks_session_close(self):
		session = frappe.new_doc("Cashier Session")
		session.name = "SESSION-1"
		session.status = "Open"

		def exists(doctype, filters):
			return doctype == "Shift Expense"

		with patch("frappe.db.sql"), patch.object(session, "reload"), patch("frappe.db.exists", side_effect=exists):
			with self.assertRaisesRegex(frappe.ValidationError, "pending Shift Expense"):
				session.begin_closing()

	def test_only_pending_or_approved_returns_reserve_source_quantity(self):
		with patch("frappe.db.sql", return_value=[frappe._dict(qty=1.5)]) as sql, \
				patch.object(POSReturn, "get_external_returned_qty", return_value=0):
			quantity = POSReturn.get_reserved_qty("SOURCE-ROW")
		self.assertEqual(quantity, 1.5)
		query = sql.call_args.args[0]
		self.assertIn("ret.status in ('Pending Approval', 'Approved')", query)
		self.assertIn("ret.docstatus < 2", query)

