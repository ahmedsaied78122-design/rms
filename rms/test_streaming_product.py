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


class TestSharedProfileBranch(unittest.TestCase):
	def test_shared_profile_uses_own_pair_but_a_durable_foreign_store_is_rejected(self):
		from rms import streaming_policy as policy

		for related, blocked in [(set(),False),({'foreign-store'},True)]:
			with (
				self.subTest(related=related),
				patch.object(frappe,'conf',frappe._dict(arab_streaming_site_role='Slave')),
				patch.object(policy,'_assignment',return_value=set()),
				patch.object(policy,'_store_branches',return_value={'A','B'}),
				patch('frappe.get_meta',return_value=frappe._dict(get_field=lambda field:frappe._dict(options='POS Opening Entry'))),
				patch('frappe.get_all',side_effect=lambda dt,**kw: ['A'] if dt=='Master Instance' else ['Company'] if dt=='Store' and 'streaming_branch' in kw.get('filters',{}) else ['s1','s2'] if dt=='Store' else list(related)),
				patch('frappe.throw',side_effect=frappe.PermissionError),
			):
				doc=frappe._dict(doctype='POS Opening Entry',name='audit-opening',company='Company',pos_profile='Shared')
				if blocked:
					with self.assertRaises(frappe.PermissionError):policy.resolve_branch(doc,{})
				else:self.assertEqual(policy.resolve_branch(doc,{}),{'A'})
