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
