import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from rms.api.pos import get_order_state


class TestPOSOrderState(unittest.TestCase):
	def test_scoped_cashier_can_detect_another_cashiers_closed_order(self):
		for status in ("Open", "Confirmed", "Paid", "Cancelled"):
			with self.subTest(status=status):
				order = SimpleNamespace(name="ORDER-4", store="STORE-1", status=status,
					docstatus=0, modified="2026-11-04 12:00:00", cashier_session="OTHER-CASHIER-SESSION")
				with patch("rms.api.pos.require_pos_role") as role, \
						patch("rms.api.pos.frappe.get_doc", return_value=order), \
						patch("rms.api.pos.assert_store_access") as access, \
						patch("rms.api.pos.require_order_scope") as scope:
					result = get_order_state("ORDER-4")
				role.assert_called_once()
				access.assert_called_once_with("STORE-1")
				scope.assert_called_once_with(order)
				self.assertEqual(result, {"name": "ORDER-4", "status": status, "modified": "2026-11-04 12:00:00",
					"is_closed": status in ("Paid", "Cancelled")})

	def test_order_state_does_not_bypass_store_permissions(self):
		order = SimpleNamespace(name="ORDER-4", store="DENIED")
		with patch("rms.api.pos.require_pos_role"), \
				patch("rms.api.pos.frappe.get_doc", return_value=order), \
				patch("rms.api.pos.assert_store_access", side_effect=frappe.PermissionError), \
				patch("rms.api.pos.require_order_scope") as scope:
			with self.assertRaises(frappe.PermissionError):
				get_order_state("ORDER-4")
			scope.assert_not_called()

	def test_order_state_does_not_bypass_brand_or_order_type_scope(self):
		order = SimpleNamespace(name="ORDER-4", store="STORE-1")
		with patch("rms.api.pos.require_pos_role"), \
				patch("rms.api.pos.frappe.get_doc", return_value=order), \
				patch("rms.api.pos.assert_store_access"), \
				patch("rms.api.pos.require_order_scope", side_effect=frappe.PermissionError):
			with self.assertRaises(frappe.PermissionError):
				get_order_state("ORDER-4")
