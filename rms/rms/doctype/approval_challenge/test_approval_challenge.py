import unittest
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime
from frappe.utils.password import passlibctx

from rms.rms.doctype.approval_challenge.approval_challenge import ApprovalChallenge


class TestApprovalChallenge(unittest.TestCase):
	def make_challenge(self):
		challenge = frappe.new_doc("Approval Challenge")
		challenge.status = "Issued"
		challenge.code_hash = passlibctx.hash("381604")
		challenge.expires_at = add_to_date(now_datetime(), minutes=2)
		challenge.failed_attempts = 0
		return challenge

	def test_valid_code_is_consumed_once(self):
		challenge = self.make_challenge()
		with patch.object(challenge, "save"):
			challenge.verify_code("381604")
			self.assertEqual(challenge.status, "Consumed")
			self.assertIsNotNone(challenge.used_at)
			with self.assertRaisesRegex(frappe.ValidationError, "already been used"):
				challenge.verify_code("381604")

	def test_valid_code_can_be_checked_without_consuming_it(self):
		challenge = self.make_challenge()
		with patch.object(challenge, "save") as save:
			challenge.verify_code("381604", consume=False)
		self.assertEqual(challenge.status, "Issued")
		self.assertIsNone(challenge.used_at)
		save.assert_not_called()

	def test_invalid_code_increments_persisted_attempts(self):
		challenge = self.make_challenge()
		with patch.object(challenge, "save") as save, patch("frappe.db.commit") as commit:
			with self.assertRaisesRegex(frappe.ValidationError, "incorrect"):
				challenge.verify_code("000000")
		self.assertEqual(challenge.failed_attempts, 1)
		save.assert_called_once_with(ignore_permissions=True)
		commit.assert_called_once_with()

	def test_five_invalid_codes_revoke_the_challenge(self):
		challenge = self.make_challenge()
		with patch.object(challenge, "save"), patch("frappe.db.commit"):
			for _ in range(5):
				with self.assertRaisesRegex(frappe.ValidationError, "incorrect|locked"):
					challenge.verify_code("000000")
		self.assertEqual(challenge.failed_attempts, 5)
		self.assertEqual(challenge.status, "Revoked")

	def test_expired_code_cannot_be_redeemed(self):
		challenge = self.make_challenge()
		challenge.expires_at = add_to_date(now_datetime(), minutes=-1)
		with patch.object(challenge, "save"), patch("frappe.db.commit"):
			with self.assertRaisesRegex(frappe.ValidationError, "expired"):
				challenge.verify_code("381604")
		self.assertEqual(challenge.status, "Expired")
