import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

import frappe

from rms.api.pos import get_bootstrap, get_default_pos_store, get_pos_profile_for_store, get_profile_for_new_session, open_session


class TestPOSProfileAssignment(unittest.TestCase):
	def test_bootstrap_selects_the_assigned_default_store(self):
		stores = [
			frappe._dict(name="STORE-1", title="Front Counter", store_code="FC"),
			frappe._dict(name="STORE-2", title="Riverside", store_code="RV"),
		]
		with patch("rms.api.pos.require_pos_role"), \
				patch("rms.api.pos.get_pos_capabilities", return_value={}), \
				patch("rms.api.pos.frappe.get_all", return_value=stores), \
				patch("rms.api.pos.assert_store_access"), \
				patch("rms.api.pos.get_active_pos_user", return_value="POS-USER-1"), \
				patch("rms.api.pos.frappe.db.get_value", return_value="STORE-2"), \
				patch("rms.api.pos.get_user_session", return_value=None):
			self.assertEqual(get_bootstrap()["default_store"], "STORE-2")

	def test_store_selection_falls_back_to_first_allowed_store_when_none_is_default(self):
		stores = [frappe._dict(name="STORE-1"), frappe._dict(name="STORE-2")]
		with patch("rms.api.pos.get_active_pos_user", return_value="POS-USER-1"), \
				patch("rms.api.pos.frappe.db.get_value", return_value=None):
			self.assertEqual(get_default_pos_store(stores), "STORE-1")

	def test_cashier_uses_store_specific_assigned_pos_profile(self):
		with patch("rms.api.pos.get_active_pos_user", return_value="POS-USER-1"), \
				patch("rms.api.pos.frappe.db.get_value", return_value="PROFILE-CASHIER-2") as get_value:
			self.assertEqual(get_pos_profile_for_store("STORE-1", "cashier@example.com"), "PROFILE-CASHIER-2")
		self.assertEqual(get_value.call_args.args, ("POS User Store", {
			"parent": "POS-USER-1", "parenttype": "POS User", "store": "STORE-1",
		}, "pos_profile"))

	def test_cashier_without_profile_override_uses_store_default(self):
		with patch("rms.api.pos.get_active_pos_user", return_value="POS-USER-1"), \
				patch("rms.api.pos.frappe.db.get_value", side_effect=[None, "PROFILE-DEFAULT"]):
			self.assertEqual(get_pos_profile_for_store("STORE-1", "cashier@example.com"), "PROFILE-DEFAULT")

	def test_legacy_user_uses_store_default_profile(self):
		with patch("rms.api.pos.get_active_pos_user", return_value=None), \
				patch("rms.api.pos.frappe.db.get_value", return_value="PROFILE-DEFAULT"):
			self.assertEqual(get_pos_profile_for_store("STORE-1", "admin@example.com"), "PROFILE-DEFAULT")

	def test_open_session_returns_the_cashiers_existing_session(self):
		store = SimpleNamespace(name="STORE-1")
		session = Mock()
		session.as_dict.return_value = {"name": "SESSION-1", "store": "STORE-1"}
		with patch("rms.api.pos.require_pos_action"), \
				patch("rms.api.pos.assert_store_access", return_value=store), \
				patch("rms.api.pos.get_user_session", return_value=session), \
				patch("rms.api.pos.frappe.session", frappe._dict(user="cashier@example.com")):
			result = open_session("STORE-1")
		self.assertEqual(result["name"], "SESSION-1")
		self.assertTrue(result["resumed"])

	def test_open_session_uses_cashier_specific_profile_when_store_profile_is_busy(self):
		store = SimpleNamespace(name="STORE-1", company="COMPANY-1")
		profile = frappe._dict(name="PROFILE-CASHIER-2", company="COMPANY-1", payments=[])
		opening = Mock(name="opening-entry")
		opening.name = "OPEN-CASHIER-2"
		session = Mock()
		session.as_dict.return_value = {"name": "SESSION-CASHIER-2", "store": "STORE-1", "pos_profile": "PROFILE-CASHIER-2"}
		def get_doc(doctype, *args, **kwargs):
			if doctype == "POS Profile":
				return profile
			if isinstance(doctype, dict) and doctype.get("doctype") == "POS Opening Entry":
				return opening
			self.fail(f"Unexpected document lookup: {doctype}")
		with patch("rms.api.pos.require_pos_action"), \
				patch("rms.api.pos.assert_store_access", return_value=store), \
				patch("rms.api.pos.get_user_session", return_value=None), \
				patch("rms.api.pos.frappe.parse_json", return_value={}), \
				patch("rms.api.pos.frappe.get_all", return_value=[]), \
				patch("rms.api.pos.get_profile_for_new_session", return_value="PROFILE-CASHIER-2") as resolve_profile, \
				patch("rms.api.pos.frappe.get_doc", side_effect=get_doc), \
				patch("rms.api.pos.nowdate", return_value="2026-10-20"), \
				patch("rms.api.pos.now_datetime", return_value="2026-10-20 12:00:00"), \
				patch("rms.api.pos.create_cashier_session_for_opening", return_value=session) as create_session, \
				patch("rms.api.pos.frappe.session", frappe._dict(user="cashier2@example.com")):
			result = open_session("STORE-1", "{}")
		self.assertEqual(result["pos_profile"], "PROFILE-CASHIER-2")
		resolve_profile.assert_called_once_with(store, "cashier2@example.com")
		opening.insert.assert_called_once_with(ignore_permissions=True)
		opening.submit.assert_called_once_with()
		create_session.assert_called_once_with("STORE-1", "PROFILE-CASHIER-2", opening, {})

	def test_busy_store_default_gets_a_cashier_specific_profile(self):
		store = SimpleNamespace(name="STORE-1", company="COMPANY-1")
		assignment = SimpleNamespace(store="STORE-1", pos_profile="PROFILE-DEFAULT")
		user_doc = SimpleNamespace(stores=[assignment], save=Mock())
		base_profile = Mock()
		profile_copy = Mock(company="COMPANY-1", disabled=0, name=None)
		with patch("rms.api.pos.get_pos_profile_for_store", return_value="PROFILE-DEFAULT"), \
				patch("rms.api.pos.frappe.db.get_value", side_effect=[frappe._dict(name="OPEN-1", user="other@example.com"), "Cashier One"]), \
				patch("rms.api.pos.get_active_pos_user", return_value="POS-USER-1"), \
				patch("rms.api.pos.frappe.db.exists", return_value=False), \
				patch("rms.api.pos.frappe.copy_doc", return_value=profile_copy), \
				patch("rms.api.pos.frappe.get_doc", side_effect=[base_profile, user_doc]), \
				patch("rms.api.pos.frappe.session", frappe._dict(user="cashier@example.com")):
			result = get_profile_for_new_session(store, "cashier@example.com")
		self.assertTrue(result.startswith("RMS-store-1-cashier-one-"))
		profile_copy.insert.assert_called_once_with(ignore_permissions=True)
		user_doc.save.assert_called_once_with(ignore_permissions=True)
		self.assertEqual(assignment.pos_profile, result)

	def test_busy_store_default_explains_profile_assignment_for_legacy_user(self):
		store = SimpleNamespace(name="STORE-1", company="COMPANY-1")
		with patch("rms.api.pos.get_pos_profile_for_store", return_value="PROFILE-DEFAULT"), \
				patch("rms.api.pos.frappe.db.get_value", side_effect=[frappe._dict(name="OPEN-1", user="cashier@example.com"), "Other Cashier"]), \
				patch("rms.api.pos.get_active_pos_user", return_value=None):
			with self.assertRaisesRegex(frappe.ValidationError, "separate POS Profile"):
				get_profile_for_new_session(store, "legacy@example.com")
