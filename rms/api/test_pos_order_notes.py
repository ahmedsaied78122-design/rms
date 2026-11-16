import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import frappe

from rms.api.pos import update_order_notes


class TestOrderNotes(unittest.TestCase):
	def setUp(self):
		stack = ExitStack()
		self.addCleanup(stack.close)
		self.order = frappe._dict(name="ORDER-1", store="STORE-1", cashier_session="SESSION-1", status="Confirmed", modified="2026-11-05 12:00:00")
		self.order.save = MagicMock()
		self.session = frappe._dict(name="SESSION-1", status="Open")
		self.permission = stack.enter_context(patch("rms.api.pos.require_pos_action"))
		stack.enter_context(patch("rms.api.pos.assert_store_access"))
		stack.enter_context(patch("rms.api.pos.require_order_scope"))
		stack.enter_context(patch("rms.api.pos.get_user_session", return_value=self.session))
		self.get_doc = stack.enter_context(patch("rms.api.pos.frappe.get_doc", return_value=self.order))

	def test_comment_is_saved_on_whole_order(self):
		result = update_order_notes("ORDER-1", "  تجهيز الطلب الساعة ٣  ", expected_modified=self.order.modified)
		self.get_doc.assert_called_once_with("POS Order", "ORDER-1", for_update=True)
		self.assertEqual(result["order_notes"], "تجهيز الطلب الساعة ٣")
		self.order.save.assert_called_once_with(ignore_permissions=True)

	def test_clear_comment_and_cross_session_permissions(self):
		self.order.cashier_session = "OTHER-SESSION"
		update_order_notes("ORDER-1", "")
		self.assertEqual(self.order.order_notes, "")
		self.permission.assert_any_call("can_edit_open_orders")

	def test_terminal_orders_invalid_text_and_stale_updates_are_rejected(self):
		for status, text, modified in (("Paid", "note", None), ("Cancelled", "note", None),
			("Confirmed", None, None), ("Confirmed", "x"*2001, None), ("Confirmed", "note", "2026-11-05 11:00:00")):
			self.order.status = status
			with self.subTest(status=status, modified=modified), self.assertRaises((frappe.ValidationError,frappe.PermissionError)):
				update_order_notes("ORDER-1", text, modified)
		self.order.save.assert_not_called()

	def test_order_scope_is_required(self):
		with patch("rms.api.pos.require_order_scope", side_effect=frappe.PermissionError), self.assertRaises(frappe.PermissionError):
			update_order_notes("ORDER-1", "note")
		self.order.save.assert_not_called()
