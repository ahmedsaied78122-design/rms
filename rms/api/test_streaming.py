import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class TestRMSStreamingPayload(unittest.TestCase):
	@staticmethod
	def serializer():
		try:
			return importlib.import_module("rms.streaming").build_sync_payload
		except (ImportError, AttributeError):
			return None

	def test_product_snapshot_contains_only_versioned_sync_fields(self):
		build_sync_payload = self.serializer()
		if not build_sync_payload:
			self.fail("RMS streaming payload serializer is not implemented")

		payload = build_sync_payload("Selling Product", {
			"name": "Koshari Classic",
			"modified": "2026-10-20 12:00:00",
			"title": "Koshari Classic",
			"item": "Koshari Classic",
			"product_category": "Egyptian Classics",
			"uom": "Nos",
			"enabled": 1,
			"selling_price": 128,
			"image": "/private/files/menu-photo.jpg",
			"default_warehouse": "Stores - NTH",
			"default_store_company": "Nile Table Hospitality",
			"owner": "mariam.elsayed.demo@example.com",
			"selling_prices": [{
				"store": "Zamalek Riverside Kitchen",
				"order_type": "Dine In",
				"restaurant_brand": "Bayt El Nile",
				"selling_price": 128,
				"priority": 1,
				"cost": 40,
			}],
			"recipe": [{
				"item": "Koshari Base Mix",
				"qty": 1,
				"uom": "Kg",
				"cost": 40,
				"sub_recipe": 1,
				"multi_level": 0,
				"owner": "mariam.elsayed.demo@example.com",
			}],
		}, action="update")

		self.assertEqual(payload, {
			"schema_version": 1,
			"doctype": "Selling Product",
			"name": "Koshari Classic",
			"modified": "2026-10-20 12:00:00",
			"action": "update",
			"data": {
				"title": "Koshari Classic",
				"item": "Koshari Classic",
				"product_category": "Egyptian Classics",
				"uom": "Nos",
				"enabled": 1,
				"selling_price": 128,
				"selling_prices": [{
					"store": "Zamalek Riverside Kitchen",
					"order_type": "Dine In",
					"restaurant_brand": "Bayt El Nile",
					"selling_price": 128,
					"priority": 1,
				}],
				"recipe": [{
					"item": "Koshari Base Mix",
					"qty": 1,
					"sub_recipe": 1,
					"multi_level": 0,
				}],
			},
		})

	def test_delete_event_has_identity_but_no_stale_record_data(self):
		build_sync_payload = self.serializer()
		if not build_sync_payload:
			self.fail("RMS streaming payload serializer is not implemented")

		payload = build_sync_payload("Restaurant Brand", {
			"name": "Bayt El Nile",
			"title": "Bayt El Nile",
			"brand_code": "BTN",
			"enabled": 0,
		}, action="delete")
		self.assertEqual(payload["action"], "delete")
		self.assertEqual(payload["data"], {})
		self.assertEqual(payload["name"], "Bayt El Nile")

	def test_unapproved_doctype_cannot_be_serialized(self):
		build_sync_payload = self.serializer()
		if not build_sync_payload:
			self.fail("RMS streaming payload serializer is not implemented")

		with self.assertRaises(ValueError):
			build_sync_payload("POS Invoice", {"name": "ACC-PSINV-2026-00001"}, action="update")

	def test_rename_preserves_both_document_identities(self):
		build_sync_payload = self.serializer()
		if not build_sync_payload:
			self.fail("RMS streaming payload serializer is not implemented")

		payload = build_sync_payload("Restaurant Brand", {"name": "Bayt El Nile New", "title": "Bayt El Nile"},
			action="rename", previous_name="Bayt El Nile Old")
		self.assertEqual(payload["name"], "Bayt El Nile New")
		self.assertEqual(payload["previous_name"], "Bayt El Nile Old")

	def test_idempotency_key_changes_with_event_action(self):
		if not self.serializer():
			self.fail("RMS streaming payload serializer is not implemented")
		from rms.streaming import make_idempotency_key

		common = ("site-a", "Restaurant Brand", "Bayt El Nile", "2026-10-20 12:00:00")
		self.assertNotEqual(make_idempotency_key(*common, "insert"), make_idempotency_key(*common, "delete"))

	def test_disabled_local_capture_does_not_create_an_event(self):
		if not self.serializer():
			self.fail("RMS streaming payload serializer is not implemented")
		from rms.streaming import capture_doc_event

		doc = SimpleNamespace(doctype="Restaurant Brand", name="Bayt El Nile", modified="2026-10-20 12:00:00", flags={})
		with patch("rms.streaming.frappe.db.exists", return_value=True), \
				patch("rms.streaming.frappe.db.get_single_value", return_value=0), \
				patch("rms.streaming.frappe.get_doc") as get_doc:
			capture_doc_event(doc, "on_update")
		get_doc.assert_not_called()
