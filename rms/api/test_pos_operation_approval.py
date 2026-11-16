import copy
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import add_to_date, now_datetime
from frappe.utils.password import passlibctx

from rms import pos_operation_approval as approval


class TestPOSOperationApproval(unittest.TestCase):
	def context(self, action='Void', waste=0):
		return dict(action=action, subject='ORDER-1', store='STORE-1', requester='cashier@example.com',
			version='v1', cashier_session='SESSION-1', payload=dict(items=[dict(item_name='ROW-1', qty=1)],
				is_waste=waste, comment='بدون ملح', action_reason='REASON-1'))

	def test_each_operation_requires_base_permission_and_separate_waste_permission(self):
		for action, (base, waste) in approval.PERMISSIONS.items():
			for base_allowed in (False, True):
				for waste_allowed in (False, True):
					for is_waste in (0, 1):
						with self.subTest(action=action, base=base_allowed, waste=waste_allowed, selected=is_waste), \
								patch('rms.api.pos.get_pos_capabilities', return_value={base: base_allowed, waste: waste_allowed}), \
								patch.object(approval, 'eligible_managers', return_value=[dict(user='manager@example.com')]):
							result = approval.authorize(self.context(action, is_waste))
							self.assertEqual(bool(result.get('requires_manager_authorization')), not (base_allowed and (not is_waste or waste_allowed)))

	def test_otp_fingerprint_binds_all_operation_terms(self):
		context = self.context()
		for field, value in [('subject', 'ORDER-2'), ('requester', 'other@example.com'), ('store', 'STORE-2'), ('cashier_session', 'SESSION-2'), ('version', 'v2')]:
			changed = copy.deepcopy(context); changed[field] = value
			self.assertNotEqual(approval.digest(context), approval.digest(changed))
		for field, value in [('comment', 'changed'), ('is_waste', 1), ('action_reason', 'OTHER'), ('items', [dict(item_name='ROW-1', qty=2)])]:
			changed = copy.deepcopy(context); changed['payload'][field] = value
			self.assertNotEqual(approval.digest(context), approval.digest(changed))
		self.assertEqual(approval.digest(context), approval.digest(dict(reversed(list(context.items())))))

	def test_manager_must_be_different_enabled_authorized_and_store_scoped(self):
		context = self.context()
		self.assertFalse(approval.manager_allowed(context['requester'], context))
		with patch('frappe.db.get_value', return_value=None):
			self.assertFalse(approval.manager_allowed('manager@example.com', context))
		with patch('frappe.db.get_value', return_value='manager@example.com'), patch('frappe.get_roles', return_value=['POS Manager']), \
				patch('rms.api.pos._user_has_store_access', return_value=True), patch('rms.api.pos.get_pos_capabilities', return_value={'can_void_items':False}):
			self.assertFalse(approval.manager_allowed('manager@example.com', context))

	def test_wrong_password_attempts_are_rate_limited_outside_the_transaction(self):
		cache = MagicMock();cache.get_value.return_value=0
		with patch('frappe.cache', return_value=cache):
			with self.assertRaises(frappe.ValidationError): approval._check_secret('wrong', 'correct', 'KEY')
			cache.set_value.assert_called_once_with('KEY', 1, expires_in_sec=300)
			cache.get_value.return_value=5
			with self.assertRaises(frappe.ValidationError): approval._check_secret('correct', 'correct', 'KEY')

	def test_password_and_hashed_otp_success_clear_failure_counter(self):
		cache=MagicMock();cache.get_value.return_value=1
		with patch('frappe.cache', return_value=cache):
			approval._check_secret('temporary-test', 'temporary-test', 'KEY')
			approval._check_secret('123456', passlibctx.hash('123456'), 'OTP', hashed=True)
		cache.delete_value.assert_any_call('KEY');cache.delete_value.assert_any_call('OTP')

	def test_otp_without_exact_issued_context_is_rejected(self):
		with patch('rms.api.pos.get_pos_capabilities', return_value={}), patch.object(approval, 'manager_allowed', return_value=True), \
				patch('frappe.get_all', return_value=[]):
			with self.assertRaisesRegex(frappe.ValidationError, 'No current code matches'):
				approval.authorize(self.context(), 'manager@example.com', approval_code='123456')

	def test_code_is_locked_rechecked_and_consumed_without_commit(self):
		challenge=MagicMock(name='challenge');challenge.name='CHALLENGE-1';challenge.status='Issued'
		challenge.expires_at=add_to_date(now_datetime(),minutes=5);challenge.code_hash=passlibctx.hash('123456')
		with patch('rms.api.pos.get_pos_capabilities', return_value={}), patch.object(approval, 'manager_allowed', return_value=True), \
				patch('frappe.get_all', return_value=['CHALLENGE-1']), patch('frappe.get_doc', return_value=challenge) as get_doc, \
				patch.object(approval,'_check_secret') as check, patch('frappe.db.commit') as commit:
			result=approval.authorize(self.context(),'manager@example.com',approval_code='123456')
		get_doc.assert_called_once_with('Approval Challenge','CHALLENGE-1',for_update=True)
		check.assert_called_once_with('123456',challenge.code_hash,'rms:operation-otp:CHALLENGE-1',hashed=True)
		self.assertEqual(challenge.status,'Consumed');self.assertEqual(result['approval_challenge'],'CHALLENGE-1')
		commit.assert_not_called()

	def test_expired_or_concurrently_consumed_code_is_rejected_after_lock(self):
		for status, expiry in [('Consumed',add_to_date(now_datetime(),minutes=5)),('Issued',add_to_date(now_datetime(),minutes=-1))]:
			challenge=MagicMock(status=status,expires_at=expiry)
			with patch('rms.api.pos.get_pos_capabilities', return_value={}), patch.object(approval, 'manager_allowed', return_value=True), \
					patch('frappe.get_all', return_value=['CHALLENGE-1']), patch('frappe.get_doc', return_value=challenge):
				with self.assertRaisesRegex(frappe.ValidationError,'expired or was already used'):
					approval.authorize(self.context(),'manager@example.com',approval_code='123456')
			challenge.save.assert_not_called()

	def test_comments_are_strings_limited_to_one_thousand_characters(self):
		self.assertEqual(approval.clean_comment(' تعليق '),'تعليق')
		for value in (None, {}, ['text'], 'x'*1001):
			with self.assertRaises(frappe.ValidationError):approval.clean_comment(value)

	def test_approval_code_is_delivered_to_manager_bell_with_escaped_details(self):
		context = self.context()
		context['payload']['comment'] = '<script>comment</script>'
		context['payload']['items'][0]['title'] = '<Rice>'
		import json
		doc = frappe._dict(name='APPROVAL-1', operation_payload=json.dumps(context), approver='manager@example.com',
			requester='cashier@example.com', subject_name='ORDER-1', store='STORE-1', action='POS Void')
		with patch('frappe.db.get_value', return_value='Customer request'), patch('frappe.get_doc') as create:
			approval._notify_approval_code(doc, '123456')
		notification = create.call_args.args[0]
		self.assertEqual(notification['doctype'], 'Notification Log')
		self.assertEqual(notification['for_user'], 'manager@example.com')
		self.assertEqual(notification['type'], 'Alert')
		self.assertEqual(notification['document_name'], 'APPROVAL-1')
		self.assertIn('123456', notification['subject'])
		self.assertIn('&lt;Rice&gt;', notification['email_content'])
		self.assertNotIn('<script>', notification['email_content'])
		create.return_value.insert.assert_called_once_with(ignore_permissions=True)

	def test_request_delivers_code_without_returning_secret_to_cashier(self):
		context=self.context()
		doc=MagicMock();doc.name='APPROVAL-1';doc.expires_at=add_to_date(now_datetime(),minutes=5)
		with patch('rms.api.pos.require_pos_role'), patch.object(approval,'_rebuild',return_value=context), \
				patch.object(approval,'manager_allowed',return_value=True), patch('frappe.db.get_value',return_value=None), \
				patch.object(approval,'_new_challenge',return_value=doc), patch.object(approval,'_set_issued_code',return_value='123456'), \
				patch.object(approval,'_notify_approval_code') as notify:
			result=approval.request_pos_operation_approval(context,'manager@example.com')
		notify.assert_called_once_with(doc,'123456')
		self.assertEqual(result['delivered_to'],'manager@example.com')
		self.assertNotIn('123456',str(result))

	def test_repeated_request_does_not_duplicate_code_or_notification(self):
		context=self.context()
		existing=frappe._dict(name='APPROVAL-1',status='Issued',expires_at=add_to_date(now_datetime(),minutes=5))
		with patch('rms.api.pos.require_pos_role'), patch.object(approval,'_rebuild',return_value=context), \
				patch.object(approval,'manager_allowed',return_value=True), patch('frappe.db.get_value',return_value=existing), \
				patch.object(approval,'_notify_approval_code') as notify, patch.object(approval,'_new_challenge') as create:
			result=approval.request_pos_operation_approval(context,'manager@example.com')
		self.assertEqual(result['name'],existing.name)
		notify.assert_not_called();create.assert_not_called()

	def test_frappe_controller_permission_argument_allows_authorized_manager_read(self):
		from rms.api import pos
		doc=frappe._dict(store='STORE-1',owner='cashier@example.com')
		with patch('frappe.get_roles',return_value=['POS Manager']),patch('rms.api.pos._user_has_store_access',return_value=True):
			for controller in (pos.has_approval_challenge_permission,pos.has_shift_expense_permission,pos.has_pos_return_permission):
				self.assertTrue(frappe.call(controller,doc=doc,user='manager@example.com',ptype='read'))
			self.assertFalse(frappe.call(pos.has_approval_challenge_permission,doc=doc,user='manager@example.com',ptype='write'))
		with patch('frappe.get_roles',return_value=['POS Manager']),patch('rms.api.pos._user_has_store_access',return_value=False):
			self.assertFalse(frappe.call(pos.has_approval_challenge_permission,doc=doc,user='other@example.com',ptype='read'))
