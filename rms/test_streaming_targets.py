import unittest
from unittest.mock import Mock, patch

import frappe

from rms import streaming_targets as binding


class TestStoreConnections(unittest.TestCase):
    def test_new_store_needs_no_manual_scope(self):
        doc = Mock(name="store")
        doc.name = "Store A"
        doc.get.side_effect = lambda f: None
        doc.get_doc_before_save.return_value = None
        with (
            patch.object(
                frappe, "conf", frappe._dict(arab_streaming_site_role="Master")
            ),
            patch("frappe.get_doc") as create,
        ):
            binding.ensure_store_scope(doc)
            self.assertTrue(doc.streaming_branch.startswith("RMS-STORE-"))
            self.assertEqual(create.call_args.args[0]["branch"], doc.streaming_branch)
            self.assertEqual(create.call_args.args[0]["custom_streaming_enabled"], 1)

    def test_existing_store_keeps_its_original_pair_identity(self):
        doc = Mock()
        doc.name = "Store A"
        doc.streaming_branch = "MAADI"
        doc.get.return_value = "MAADI"
        doc.get_doc_before_save.return_value = frappe._dict(streaming_branch="MAADI")
        with (
            patch.object(
                frappe, "conf", frappe._dict(arab_streaming_site_role="Master")
            ),
            patch("frappe.db.get_value", return_value=1),
            patch("frappe.get_doc") as create,
        ):
            binding.ensure_store_scope(doc)
            create.assert_not_called()
            self.assertEqual(doc.streaming_branch, "MAADI")

    def test_operator_cannot_supply_another_store_scope(self):
        doc = Mock()
        doc.name = "Store A"
        doc.streaming_branch = "foreign"
        doc.get.return_value = "foreign"
        doc.get_doc_before_save.return_value = None
        with (
            patch.object(
                frappe, "conf", frappe._dict(arab_streaming_site_role="Master")
            ),
            self.assertRaises(frappe.ValidationError),
        ):
            binding.ensure_store_scope(doc)

    def test_receiver_preserves_the_masters_scope_without_creating_one(self):
        doc = Mock()
        with (
            patch.object(
                frappe, "conf", frappe._dict(arab_streaming_site_role="Slave")
            ),
            patch("frappe.get_doc") as create,
        ):
            binding.ensure_store_scope(doc)
            create.assert_not_called()

    def test_store_catalog_excludes_an_already_assigned_store(self):
        rows = [
            frappe._dict(name="A", title="A", streaming_branch="used"),
            frappe._dict(name="B", title="B", streaming_branch="free"),
        ]
        with (
            patch("frappe.get_all", return_value=["used"]),
            patch("frappe.get_list", return_value=rows),
        ):
            data = binding.provide("choices")
            self.assertEqual(data["label"], "Store")
            self.assertEqual(data["targets"], [{"name": "B", "label": "B"}])

    def test_disabled_occupied_or_unauthorized_store_cannot_be_selected(self):
        store = Mock(enabled=0, streaming_branch="scope")
        with (
            patch("frappe.get_doc", return_value=store),
            patch("frappe.db.exists", return_value=False),
        ):
            with self.assertRaises(frappe.PermissionError):
                binding.provide("resolve", target="A")
            store.enabled = 1
            with (
                patch("frappe.db.exists", return_value=True),
                self.assertRaises(frappe.PermissionError),
            ):
                binding.provide("resolve", target="A")
            store.check_permission.side_effect = frappe.PermissionError
            with self.assertRaises(frappe.PermissionError):
                binding.provide("resolve", target="A")

    def test_target_resolution_uses_the_stores_saved_scope(self):
        store = Mock(enabled=1, streaming_branch="saved-scope")
        with (
            patch("frappe.get_doc", return_value=store),
            patch("frappe.db.exists", return_value=False),
        ):
            self.assertEqual(
                binding.provide("resolve", target="A"), {"branch": "saved-scope"}
            )
            store.check_permission.assert_called_once_with("read")

    def test_existing_slave_instance_displays_its_store(self):
        doc = frappe._dict(doctype="Slave Instance", restaurant_branch="MAADI")
        with patch("frappe.db.get_value", return_value="Store A"):
            self.assertEqual(
                binding.provide("describe", document=doc),
                {
                    "doctype": "Store",
                    "label": "Store",
                    "name": "Store A",
                    "local": True,
                },
            )
