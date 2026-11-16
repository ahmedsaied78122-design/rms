import json
import unittest
from unittest.mock import Mock,patch
import frappe
from frappe.utils import add_to_date,now_datetime
from frappe.utils.password import passlibctx
from rms.approval_notifications import get_approval_details


class TestApprovalPopup(unittest.TestCase):
	def setUp(self):
		from contextlib import ExitStack
		stack=ExitStack();self.addCleanup(stack.close)
		self.version=str(now_datetime())
		self.payload=dict(currency='EGP',total_before=228,total_after=34.2,discount_value=85,discount_type='Percentage',order_modified=self.version,comment='Customer request',items=[])
		self.doc=frappe._dict(name='APPROVAL-1',action='POS Order Discount',subject_name='ORDER-1',subject_doctype='POS Order',
			store='STORE-1',requester='cashier@example.com',approver='manager@example.com',status='Issued',creation=self.version,
			expires_at=add_to_date(now_datetime(),minutes=5),code_hash=passlibctx.hash('123456'),operation_payload=json.dumps({'payload':self.payload}),check_permission=Mock())
		stack.enter_context(patch('rms.api.pos.require_pos_role'))
		stack.enter_context(patch('frappe.session',frappe._dict(user='manager@example.com')))
		stack.enter_context(patch('frappe.get_doc',return_value=self.doc))
		self.value=stack.enter_context(patch('frappe.db.get_value',side_effect=lambda doctype,*args,**kwargs:self.version if doctype=='POS Order' else 'Cashier'))
		self.logs=stack.enter_context(patch('frappe.get_all',return_value=[frappe._dict(name='NOTICE-1',subject='Approval code 123456',title='Approval code 123456')]))

	def test_selected_approver_gets_verified_code_and_original_money_snapshot(self):
		result=get_approval_details(challenge_name='APPROVAL-1')
		self.assertEqual(result['code'],'123456');self.assertEqual(result['payload']['discount_value'],85)
		self.assertEqual(result['payload']['total_before'],228);self.assertTrue(result['historical_snapshot'])
		self.doc.check_permission.assert_called_once_with('read')

	def test_requester_cannot_fetch_code_even_with_administrator_session(self):
		with patch('frappe.session',frappe._dict(user='Administrator')):
			with self.assertRaises(frappe.PermissionError):get_approval_details(challenge_name='APPROVAL-1')
		self.logs.assert_not_called()

	def test_expired_and_consumed_codes_are_hidden(self):
		self.doc.expires_at=add_to_date(now_datetime(),minutes=-1)
		result=get_approval_details(challenge_name='APPROVAL-1');self.assertIsNone(result['code']);self.assertEqual(result['status'],'Expired')
		self.doc.status='Consumed';result=get_approval_details(challenge_name='APPROVAL-1')
		self.assertIsNone(result['code']);self.assertEqual(result['status'],'Consumed')
		self.logs.assert_not_called()

	def test_changed_order_hides_code_and_keeps_original_requested_amounts(self):
		self.value.side_effect=lambda doctype,*args,**kwargs:str(add_to_date(self.version,seconds=1)) if doctype=='POS Order' else 'Cashier'
		result=get_approval_details(challenge_name='APPROVAL-1')
		self.assertIsNone(result['code']);self.assertEqual(result['status'],'Changed');self.assertEqual(result['payload']['total_after'],34.2)
		self.logs.assert_not_called()
