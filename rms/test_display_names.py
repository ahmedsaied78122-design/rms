"""Display-name edits retain link identities and stock item ownership."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import frappe
from frappe.model.naming import set_new_name
from rms.naming import TITLE_MASTERS, name_from_title, validate_display_title
from rms.rms.doctype.selling_product.selling_product import SellingProduct


class TestDisplayNames(unittest.TestCase):
	def test_new_master_uses_its_entered_title_through_native_naming(self):
		for dt in TITLE_MASTERS:
			with self.subTest(doctype=dt):
				doc = frappe.get_doc(dict(doctype=dt, title="  New display name  ", __islocal=1))
				set_new_name(doc)
				self.assertEqual(doc.name, "New display name")
				self.assertEqual(doc.title, "New display name")

	def test_native_validation_does_not_replace_an_edited_title_with_old_id(self):
		for dt in TITLE_MASTERS:
			with self.subTest(doctype=dt):
				doc = frappe.get_doc(dict(doctype=dt, name="EXISTING-ID", title="  Updated name  "))
				validate_display_title(doc)
				doc._sync_autoname_field()
				self.assertEqual(doc.title, "Updated name")
				self.assertEqual(doc.name, "EXISTING-ID")
				self.assertTrue(doc.meta.show_title_field_in_link)

	def test_blank_or_whitespace_name_is_rejected(self):
		for value in (None, "", "  "):
			with self.assertRaises(frappe.ValidationError):
				name_from_title(frappe._dict(title=value))

	def test_numeric_display_name_is_not_treated_as_empty(self):
		doc = frappe._dict(title=0)
		name_from_title(doc)
		self.assertEqual(doc.title, "0")
		self.assertEqual(doc.name, "0")

	def test_product_update_syncs_item_label_without_renaming_item_or_links(self):
		product = frappe.get_doc(dict(doctype="Selling Product", name="EXISTING-ID", title="New product name", item="STOCK-ITEM-1", enabled=1, allow_negative_stock=0))
		with patch("frappe.db.exists", return_value=True), patch("frappe.db.set_value") as update, patch.object(product, "sync_erpnext_prices"):
			SellingProduct.on_update(product)
		update.assert_called_once_with("Item", "STOCK-ITEM-1", {"item_name":"New product name", "disabled":0, "allow_negative_stock":0}, update_modified=False)
		self.assertEqual(product.name, "EXISTING-ID")
		self.assertEqual(product.item, "STOCK-ITEM-1")

	def test_other_product_edits_do_not_overwrite_a_separate_stock_label(self):
		product = frappe.get_doc(dict(doctype="Selling Product", name="PRODUCT-1", title="Same name", item="ITEM-1", enabled=1))
		with patch("frappe.db.exists", return_value=True), patch("frappe.db.set_value") as update, patch.object(product, "has_value_changed", return_value=False), patch.object(product, "sync_erpnext_prices"):
			product.on_update()
		self.assertNotIn("item_name", update.call_args.args[2])

	def test_metadata_creation_hooks_preserve_local_change_capture(self):
		from rms.hooks import doc_events
		for dt in TITLE_MASTERS:
			self.assertEqual(doc_events[dt]["autoname"], "rms.naming.name_from_title")
			self.assertEqual(doc_events[dt]["before_validate"], "rms.naming.validate_display_title")
			from rms.streaming import doc_events as capture_events
			for event, handler in capture_events.get(dt, {}).items():
				self.assertEqual(doc_events[dt][event], handler)
