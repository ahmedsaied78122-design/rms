import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from rms import interface_preferences


class TestInterfacePreferences(unittest.TestCase):
	def setUp(self):
		self.flags_patch = patch.object(frappe.local, "flags", frappe._dict(in_test=False), create=True)
		self.flags_patch.start()
		self.addCleanup(self.flags_patch.stop)

	def fake_runtime(self, user):
		def reject(message, error):
			raise error(message)
		return SimpleNamespace(session=SimpleNamespace(user=user), db=SimpleNamespace(set_value=Mock()),
			clear_cache=Mock(), throw=reject, PermissionError=frappe.PermissionError,
			ValidationError=frappe.ValidationError)

	def test_language_changes_only_the_authenticated_users_language(self):
		for language in ("ar", "en"):
			fake = self.fake_runtime("preview@example.invalid")
			with patch.object(interface_preferences, "frappe", fake):
				self.assertEqual(interface_preferences.set_language(language), {"language": language})
			fake.db.set_value.assert_called_once_with("User", "preview@example.invalid", "language", language, update_modified=False)
			fake.clear_cache.assert_called_once_with(user="preview@example.invalid")

	def test_guests_cannot_write_preferences(self):
		for user in ("Guest", None):
			fake = self.fake_runtime(user)
			with patch.object(interface_preferences, "frappe", fake), patch.object(interface_preferences, "_", lambda text: text):
				with self.assertRaises(frappe.PermissionError):
					interface_preferences.set_language("ar")
			fake.db.set_value.assert_not_called()

	def test_invalid_languages_cannot_trigger_any_write(self):
		for language in (None, "fr", "ar-SA", {"user": "Administrator"}):
			fake = self.fake_runtime("preview@example.invalid")
			with patch.object(interface_preferences, "frappe", fake), patch.object(interface_preferences, "_", lambda text: text):
				with self.assertRaises(frappe.ValidationError):
					interface_preferences.set_language(language)
			fake.db.set_value.assert_not_called()
			fake.clear_cache.assert_not_called()

	def test_endpoint_is_authenticated_and_post_only(self):
		method = interface_preferences.set_language
		self.assertNotIn(method, frappe.guest_methods)
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[method], ["POST"])

	def test_animated_splash_preserves_the_existing_brand_context(self):
		context = frappe._dict(apps=[{"name": "erpnext", "title": "ERPNext"}])
		with patch("rms.branding._", lambda text: text):
			interface_preferences.website_context(context)
		self.assertEqual(context.app_name, "RMS")
		self.assertEqual(context.apps[0]["title"], "Management")
		self.assertEqual(context.splash_image, "/assets/rms/images/rms-loading.svg")
