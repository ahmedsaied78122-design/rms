import unittest
from unittest.mock import patch

import frappe


class TestCashierSessionProfileBinding(unittest.TestCase):
	def session(self):
		doc = frappe.new_doc("Cashier Session")
		doc.update(dict(name="SESSION-1", user="cashier@example.com", store="STORE-1",
			pos_profile="ORIGINAL-PROFILE", pos_opening_entry="OPENING-1", status="Open"))
		return doc

	def validate(self, doc, previous=None, assigned="NEW-PROFILE", store_profile="ORIGINAL-PROFILE", **overrides):
		def get_value(doctype, name, fieldname, **kwargs):
			values = {
				"Store": frappe._dict(company="COMPANY-1", pos_profile=store_profile, enabled=1),
				"POS User Store": assigned,
				"POS Profile": frappe._dict(company="COMPANY-1", disabled=0),
				"POS Opening Entry": frappe._dict(company="COMPANY-1", pos_profile=doc.pos_profile,
					user=doc.user, status="Open"),
				"User": 1,
			}
			values.update(overrides)
			return values[doctype]
		with patch.object(doc, "get_doc_before_save", return_value=previous), \
			patch("rms.api.pos.get_active_pos_user", return_value="POS-USER-1"), \
			patch("frappe.db.get_value", side_effect=get_value), \
			patch("frappe.db.exists", return_value=True):
			doc.validate_context()

	def test_existing_session_keeps_original_profile_after_assignment_changes(self):
		doc = self.session()
		self.validate(doc, previous=self.session())

	def test_existing_session_keeps_profile_after_store_default_changes(self):
		doc = self.session()
		self.validate(doc, previous=self.session(), assigned=None, store_profile="NEW-DEFAULT")

	def test_new_session_must_use_current_cashier_assignment(self):
		with self.assertRaisesRegex(frappe.ValidationError, "assigned to this POS User"):
			self.validate(self.session())

	def test_new_session_without_assignment_must_use_store_default(self):
		with self.assertRaisesRegex(frappe.ValidationError, "assigned to this Store"):
			self.validate(self.session(), assigned=None, store_profile="NEW-DEFAULT")

	def test_existing_session_identity_cannot_change(self):
		for field in ("store", "user", "pos_profile", "pos_opening_entry"):
			with self.subTest(field=field):
				doc = self.session()
				doc.set(field, "CHANGED")
				with self.assertRaisesRegex(frappe.ValidationError, "cannot be changed"):
					self.validate(doc, previous=self.session())

	def test_existing_session_still_rejects_mismatched_opening(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Opening Entry must match"):
			self.validate(self.session(), previous=self.session(), **{
				"POS Opening Entry": frappe._dict(company="COMPANY-1", pos_profile="OTHER",
					user="cashier@example.com", status="Open")})

	def test_existing_session_still_rejects_disabled_profile(self):
		with self.assertRaisesRegex(frappe.ValidationError, "must be enabled"):
			self.validate(self.session(), previous=self.session(), **{
				"POS Profile": frappe._dict(company="COMPANY-1", disabled=1)})
