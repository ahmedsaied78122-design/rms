import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import frappe
from rms.api import pos
from rms.api.pos import notify_pos_discount_approval


class TestDiscountNotifications(unittest.TestCase):
	def setUp(self):
		from contextlib import ExitStack
		stack=ExitStack();self.addCleanup(stack.close)
		stack.enter_context(patch("rms.approval_notifications.build_discount_snapshot",return_value={}))
		self.doc=SimpleNamespace(name='ORDER-1',store='STORE-1',status='Confirmed',restaurant_brand='BRAND-1',order_type='Takeaway',items=[],pos_invoice=None)
		for target, kwargs in [('require_pos_action',{}),('assert_store_access',{}),('require_order_scope',{}),
			('frappe.get_doc',{'return_value':self.doc}),('preview_order_discount',{'return_value':{'requires_manager_approval':True,'discount_scope':'Net Total'}}),
			('get_pos_discount_approvers',{'return_value':[{'user':'manager@example.com'}]}),('is_pos_scope_allowed',{'return_value':True}),
			('frappe.get_all',{'return_value':[]}),('notify_pos_discount_approval',{}),('frappe.new_doc',{})]:
			mock=stack.enter_context(patch('rms.api.pos.'+target,**kwargs))
			if target=='frappe.new_doc':self.new_doc=mock;self.challenge=mock.return_value;self.challenge.name='APPROVAL-1'
			if target=='notify_pos_discount_approval':self.notify=mock

	def request(self,**kwargs):
		return pos.request_pos_discount_approval_code('ORDER-1','manager@example.com','Percentage',20,'Customer discount',**kwargs)

	def test_request_creates_challenge_and_notifies_selected_manager_without_returning_otp(self):
		result=self.request()
		self.challenge.insert.assert_called_once_with(ignore_permissions=True)
		self.notify.assert_called_once()
		self.assertEqual(self.notify.call_args.args[0],self.challenge)
		self.assertEqual(len(self.notify.call_args.args[1]),6)
		self.assertNotIn('code',result)
		self.assertEqual(result['delivered_to'],'manager@example.com')

	def test_within_limit_discount_does_not_generate_or_notify(self):
		with patch('rms.api.pos.preview_order_discount',return_value={'requires_manager_approval':False}):
			with self.assertRaises(frappe.ValidationError):self.request()
		self.notify.assert_not_called();self.new_doc.assert_not_called()

	def test_invalid_manager_or_scope_does_not_send_code(self):
		for target, result in [('get_pos_discount_approvers',[]),('is_pos_scope_allowed',False)]:
			with patch('rms.api.pos.'+target,return_value=result):
				with self.assertRaises(frappe.PermissionError):self.request()
		self.notify.assert_not_called()

	def test_duplicate_request_reuses_challenge_without_another_notification(self):
		with patch('rms.api.pos.frappe.get_all',return_value=[frappe._dict(name='EXISTING',expires_at='2026-11-05')]),patch('rms.api.pos.frappe.db.exists',return_value=True):
			result=self.request()
		self.assertEqual(result['name'],'EXISTING');self.notify.assert_not_called()

	def test_paid_order_cannot_request_code(self):
		self.doc.status='Paid'
		with self.assertRaises(frappe.ValidationError):self.request()
		self.notify.assert_not_called()

	def test_notification_contains_code_and_discount_details_in_manager_inbox(self):
		challenge=frappe._dict(name='APPROVAL-1',approver='manager@example.com',requester='cashier@example.com',subject_name='ORDER-1',store='STORE-1')
		with patch('frappe.get_doc') as create:
			notify_pos_discount_approval(challenge,'123456','Percentage',20,'<reason>','Net Total')
		doc=create.call_args.args[0]
		self.assertEqual(doc['for_user'],'manager@example.com')
		self.assertEqual(doc['document_name'],'APPROVAL-1')
		self.assertEqual(doc['type'],'Alert')
		self.assertIn('123456',doc['subject']);self.assertIn('20%',doc['email_content'])
		self.assertIn('&lt;reason&gt;',doc['email_content'])
