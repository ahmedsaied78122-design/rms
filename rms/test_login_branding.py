import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urljoin, urlparse

import frappe
from werkzeug.wrappers import Request

from rms.www.login import get_context


class TestLoginBranding(unittest.TestCase):
	def setUp(self):
		self.previous_request = getattr(frappe.local, "request", None)
		self.previous_language = frappe.local.lang

	def tearDown(self):
		frappe.local.request = self.previous_request
		frappe.local.lang = self.previous_language

	def context_for(self, language, redirect="/apps"):
		frappe.local.lang = language
		frappe.local.request = Request.from_values(base_url="https://rms.example/", path="/login",
			query_string={"redirect-to": redirect})
		context = frappe._dict(disable_signup=1, disable_user_pass_login=1,
			login_with_email_link=1, provider_logins=[{"provider_name": "Company SSO"}])
		with patch("rms.www.login.get_standard_login_context") as native:
			result = get_context(context)
			native.assert_called_once_with(context)
		return result

	def test_both_languages_render_without_changing_authentication_choices(self):
		for language, direction in (("en", "ltr"), ("ar", "rtl")):
			with self.subTest(language=language):
				context = self.context_for(language)
				self.assertEqual(context.rms_direction, direction)
				self.assertEqual(context.app_name, "RMS")
				self.assertEqual(context.disable_signup, 1)
				self.assertEqual(context.disable_user_pass_login, 1)
				self.assertEqual(context.login_with_email_link, 1)
				self.assertEqual(context.provider_logins, [{"provider_name": "Company SSO"}])

	def test_language_switch_preserves_only_same_site_redirects(self):
		for redirect, expected in (("/apps", "/apps"), ("https://other.example/path", "/app"),
				("https://rms.example//other.example/path", "/other.example/path")):
			context = self.context_for("en", redirect)
			for language, url in context.rms_language_urls.items():
				query = parse_qs(urlparse(url).query)
				self.assertTrue(query["redirect-to"][0].startswith("/"))
				self.assertFalse(query["redirect-to"][0].startswith("//"))
				target = urlparse(urljoin("https://rms.example/", query["redirect-to"][0]))
				self.assertEqual(target.netloc, "rms.example")
				self.assertEqual(target.path, expected)
				self.assertEqual(query["_lang"], [language])

	def test_existing_session_redirect_is_preserved(self):
		with patch("rms.www.login.get_standard_login_context", side_effect=frappe.Redirect):
			with self.assertRaises(frappe.Redirect):
				get_context(frappe._dict())
