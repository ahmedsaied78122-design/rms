import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from rms.api.pos import save_order


class TestPOSOrderSync(unittest.TestCase):
	def test_stale_page_cannot_replace_newer_order_items(self):
		order = SimpleNamespace(name="ORDER-1", store="STORE-1", modified="2026-11-04 12:00:02")
		session = SimpleNamespace(name="SESSION-1", status="Open", user=frappe.session.user)
		with patch("rms.api.pos.require_pos_action"), \
				patch("rms.api.pos.assert_store_access", return_value=SimpleNamespace(name="STORE-1")), \
				patch("rms.api.pos.get_user_session", return_value=session), \
				patch("rms.api.pos.require_order_scope") as scope, \
				patch("rms.api.pos.frappe.get_doc", return_value=order) as get_doc:
			result = save_order({"name": "ORDER-1", "store": "STORE-1",
				"expected_modified": "2026-11-04 12:00:01", "items": []})
		get_doc.assert_called_once_with("POS Order", "ORDER-1", for_update=True)
		scope.assert_called_once_with(order)
		self.assertEqual(result, {"name": "ORDER-1", "conflict": True, "modified": "2026-11-04 12:00:02"})

	def test_version_conflict_does_not_bypass_order_scope(self):
		order = SimpleNamespace(name="ORDER-1", store="STORE-1", modified="2026-11-04 12:00:02")
		session = SimpleNamespace(name="SESSION-1", status="Open", user=frappe.session.user)
		with patch("rms.api.pos.require_pos_action"), \
				patch("rms.api.pos.assert_store_access", return_value=SimpleNamespace(name="STORE-1")), \
				patch("rms.api.pos.get_user_session", return_value=session), \
				patch("rms.api.pos.require_order_scope", side_effect=frappe.PermissionError), \
				patch("rms.api.pos.frappe.get_doc", return_value=order):
			with self.assertRaises(frappe.PermissionError):
				save_order({"name": "ORDER-1", "store": "STORE-1", "expected_modified": "2026-11-04 12:00:01"})
