import unittest
from unittest.mock import patch

import frappe

from rms.rms.doctype.pos_user_store.pos_user_store import POSUserStore


class TestPOSUserStore(unittest.TestCase):
	def test_assigned_profile_must_belong_to_the_store_company(self):
		row = frappe.new_doc("POS User Store")
		row.store = "STORE-1"
		row.pos_profile = "PROFILE-OTHER-COMPANY"
		with patch("frappe.db.get_value", side_effect=[
			frappe._dict(company="COMPANY-1", enabled=1),
			frappe._dict(company="COMPANY-2", disabled=0),
		]):
			with self.assertRaisesRegex(frappe.ValidationError, "belong to the assigned Store Company"):
				row.validate()

	def test_store_default_profile_can_be_left_unset_for_legacy_assignments(self):
		row = frappe.new_doc("POS User Store")
		row.store = "STORE-1"
		row.pos_profile = None
		row.validate()
