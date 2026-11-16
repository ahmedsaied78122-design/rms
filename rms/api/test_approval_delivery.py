import unittest
from datetime import datetime
from unittest.mock import patch
import frappe
from frappe.utils import add_to_date
from rms.approval_delivery import delivery_result,can_resend,wants_resend


class TestApprovalResendPolicy(unittest.TestCase):
	def test_cooldown_and_expiry_are_reported_without_returning_secret(self):
		now=datetime(2026,11,5,16,0,30)
		doc=frappe._dict(name='APPROVAL-1',creation=add_to_date(now,seconds=-30),expires_at=add_to_date(now,seconds=270))
		with patch('rms.approval_delivery.now_datetime',return_value=now):
			data=delivery_result(doc,'manager@example.com')
			self.assertEqual(data['resend_after_seconds'],30);self.assertEqual(data['expires_in_seconds'],270)
			self.assertFalse(can_resend(doc));self.assertNotIn('code',data)
			doc.creation=add_to_date(now,seconds=-60);self.assertTrue(can_resend(doc))

	def test_resend_requires_an_explicit_valid_flag(self):
		for value in (None,False,0,'0'):self.assertFalse(wants_resend(value))
		for value in (True,1,'1'):self.assertTrue(wants_resend(value))
		for value in ('false','yes',{},2):
			with self.assertRaises(frappe.ValidationError):wants_resend(value)
