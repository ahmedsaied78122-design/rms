"""A replicated product reuses its resolved Item without permitting manual links."""
import unittest
from unittest.mock import Mock, patch

import frappe

from rms.rms.doctype.selling_product.selling_product import SellingProduct


class TestStreamingProduct(unittest.TestCase):
	def test_authenticated_replay_keeps_the_readable_dependency(self):
		product = Mock(item="master-item")
		with (
			patch("arab_streaming.streaming.context.replay_source", return_value="pairing"),
			patch("frappe.get_doc") as get_doc,
		):
			SellingProduct.create_erpnext_item(product)
			get_doc.assert_called_once_with("Item", "master-item")
			get_doc.return_value.check_permission.assert_called_once_with("read")
		self.assertEqual(product.item, "master-item")

	def test_replay_requires_read_access_to_the_item(self):
		with (
			patch("arab_streaming.streaming.context.replay_source", return_value="pairing"),
			patch("frappe.get_doc") as get_doc,
		):
			get_doc.return_value.check_permission.side_effect = frappe.PermissionError
			with self.assertRaises(frappe.PermissionError):
				SellingProduct.create_erpnext_item(Mock(item="protected-item"))

	def test_manual_item_selection_remains_rejected(self):
		with (
			patch("arab_streaming.streaming.context.replay_source", return_value=None),
			patch("frappe.get_doc") as get_doc,
			patch("frappe.throw", side_effect=frappe.ValidationError),
		):
			with self.assertRaises(frappe.ValidationError):
				SellingProduct.create_erpnext_item(Mock(item="manually-selected-item"))
			get_doc.assert_not_called()


class TestStreamingReferenceRoles(unittest.TestCase):
	def test_missing_reference_roles_have_no_desk_access_or_permission_payload(self):
		from rms.setup import ensure_streaming_reference_roles

		with patch("frappe.db", Mock()) as db, patch("frappe.get_doc") as get_doc:
			db.exists.return_value = False
			ensure_streaming_reference_roles()
			self.assertEqual(get_doc.call_count, 3)
			for call in get_doc.call_args_list:
				self.assertEqual(set(call.args[0]), {"doctype", "role_name", "desk_access"})
				self.assertEqual(call.args[0]["doctype"], "Role")
				self.assertEqual(call.args[0]["desk_access"], 0)
			self.assertEqual(get_doc.return_value.insert.call_count, 3)

	def test_existing_roles_are_never_modified(self):
		from rms.setup import ensure_streaming_reference_roles

		with patch("frappe.db", Mock()) as db, patch("frappe.get_doc") as get_doc:
			db.exists.return_value = True
			ensure_streaming_reference_roles()
			get_doc.assert_not_called()
