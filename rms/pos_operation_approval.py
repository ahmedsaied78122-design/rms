"""Operation-bound manager authorization for POS voids and returns."""
import hashlib
import hmac
import json
import secrets
from html import escape

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime
from frappe.utils.password import passlibctx

ACTIONS = {'Void': 'POS Void', 'Return': 'POS Return'}
PERMISSIONS = {'Void': ('can_void_items', 'can_void_waste'), 'Return': ('can_request_returns', 'can_return_waste')}


def clean_comment(comment):
	if not isinstance(comment, str) or len(comment) > 1000:
		frappe.throw(_('Enter a comment of up to 1000 characters.'))
	return comment.strip()


def make_context(action, subject, store, payload, version, session=None):
	return dict(action=action, subject=subject, store=store, payload=payload, version=str(version),
		requester=frappe.session.user, cashier_session=session)


def digest(context):
	return hashlib.sha256(json.dumps(context, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def eligible_managers(context):
	from rms.api import pos
	result = []
	for manager in pos.get_pos_discount_approvers(context['store'], exclude_user=context['requester']):
		if manager_allowed(manager['user'], context): result.append(manager)
	return result


def manager_allowed(user, context):
	from rms.api import pos
	if user == context['requester'] or not frappe.db.get_value('User', {'name':user, 'enabled':1}, 'name'):
		return False
	if not set(frappe.get_roles(user)) & {'POS Manager', 'System Manager'} or not pos._user_has_store_access(user, context['store']):
		return False
	caps = pos.get_pos_capabilities(user)
	permissions = PERMISSIONS[context['action']]
	if not caps.get(permissions[0]) or (context['payload']['is_waste'] and not caps.get(permissions[1])):
		return False
	order = pos.get_pos_order_for_invoice(context['subject'], ['restaurant_brand','order_type']) if context['action'] == 'Return' else frappe.db.get_value('POS Order',context['subject'],['restaurant_brand','order_type'],as_dict=True)
	return bool(order and pos.is_pos_scope_allowed('brand',order.restaurant_brand,user=user)
		and pos.is_pos_scope_allowed('order_type',order.order_type,user=user))


def _password_key(context, manager):
	return 'rms:operation-password:' + hashlib.sha256((context['requester']+'|'+manager).encode()).hexdigest()


def _check_secret(secret, expected, key, hashed=False):
	cache = frappe.cache()
	if int(cache.get_value(key) or 0) >= 5:
		frappe.throw(_('Approval is locked for five minutes after too many incorrect attempts.'))
	valid = bool(secret and expected and (passlibctx.verify(str(secret),expected) if hashed else hmac.compare_digest(str(secret),str(expected))))
	if not valid:
		cache.set_value(key,int(cache.get_value(key) or 0)+1,expires_in_sec=300)
		frappe.throw(_('The manager password or one-time code is incorrect.'))
	cache.delete_value(key)


def authorize(context, approval_approver=None, approval_password=None, approval_code=None):
	from rms.api import pos
	caps = pos.get_pos_capabilities()
	base, waste = PERMISSIONS[context['action']]
	if caps.get(base) and (not context['payload']['is_waste'] or caps.get(waste)) and not (approval_password or approval_code):
		return dict(approved_by=frappe.session.user, approval_challenge=None)
	if not approval_approver or not (approval_password or approval_code):
		return dict(requires_manager_authorization=True, approvers=eligible_managers(context), operation_context=context)
	if not manager_allowed(approval_approver, context):
		frappe.throw(_('Choose a different manager with permission for this operation and Store.'),frappe.PermissionError)
	if approval_password:
		profile=pos.get_active_pos_user(approval_approver)
		password=frappe.get_doc('POS User',profile).get_password('discount_approval_password',raise_exception=False) if profile else None
		_check_secret(approval_password,password,_password_key(context,approval_approver))
		challenge=_new_challenge(context,approval_approver,'Consumed')
		challenge.used_at=now_datetime()
		challenge.insert(ignore_permissions=True)
	else:
		names=frappe.get_all('Approval Challenge',filters=dict(subject_doctype='POS Order' if context['action']=='Void' else 'POS Invoice',
			subject_name=context['subject'],action=ACTIONS[context['action']],requester=context['requester'],approver=approval_approver,
			approval_context_hash=digest(context),status='Issued',expires_at=['>',now_datetime()]),pluck='name',order_by='creation desc',limit=1)
		if not names:frappe.throw(_('No current code matches these items, quantities, waste option and comment. Request a new code.'))
		challenge=frappe.get_doc('Approval Challenge',names[0],for_update=True)
		if challenge.status!='Issued' or get_datetime(challenge.expires_at)<=now_datetime():frappe.throw(_('This code has expired or was already used.'))
		_check_secret(approval_code,challenge.code_hash,'rms:operation-otp:'+challenge.name,hashed=True)
		challenge.status='Consumed';challenge.used_at=now_datetime();challenge.flags.from_pos_api=True;challenge.save(ignore_permissions=True)
	return dict(approved_by=approval_approver,approval_challenge=challenge.name)


def _new_challenge(context, manager, status):
	doc=frappe.get_doc(dict(doctype='Approval Challenge',store=context['store'],subject_doctype='POS Order' if context['action']=='Void' else 'POS Invoice',
		subject_name=context['subject'],action=ACTIONS[context['action']],requester=context['requester'],approver=manager,
		status=status,approval_context_hash=digest(context),operation_payload=json.dumps(context,ensure_ascii=False),expires_at=add_to_date(now_datetime(),minutes=5)))
	doc.flags.from_pos_api=True
	return doc


def _notify_approval_code(doc, code):
	"""Deliver the secret only to the selected manager's in-app notification bell."""
	context = frappe.parse_json(doc.operation_payload)
	payload = context['payload']
	title = _('Approval code {0} · {1}').format(escape(code), escape(doc.action))
	rows = ''.join('<li>{0} × {1}</li>'.format(escape(str(row.get('title') or row.get('item_name') or row.get('source_pos_invoice_item'))),
		escape(str(row['qty']))) for row in payload['items'])
	reason = frappe.db.get_value('POS Action Reason', payload['action_reason'], 'reason') or payload['action_reason']
	description = '<p><strong>{0}</strong></p><p>{1} · {2} · {3}</p><ul>{4}</ul><p>{5}</p><p>{6}</p><p>{7}</p>'.format(
		escape(code), escape(doc.requester), escape(doc.subject_name), escape(doc.store), rows,
		escape(str(reason)), escape(payload.get('comment') or ''),
		escape(_('Waste') + ' · ' if payload['is_waste'] else '') + escape(_('Valid for five minutes. Share this code only if you approve these exact items and quantities.')))
	return frappe.get_doc(dict(doctype='Notification Log', type='Alert', for_user=doc.approver,
		from_user=doc.requester, subject=title, email_content=description,
		document_type='Approval Challenge', document_name=doc.name, read=0)).insert(ignore_permissions=True)


def _set_issued_code(doc):
	code = f'{secrets.randbelow(1000000):06d}'
	doc.code_hash = passlibctx.hash(code)
	doc.status = 'Issued'
	doc.expires_at = add_to_date(now_datetime(), minutes=5)
	doc.flags.from_pos_api = True
	return code


def _rebuild(context):
	from rms.api import pos
	payload=dict(context['payload'])
	if context['action']=='Void':
		return pos.cancel_confirmed_order_items(context['subject'],payload['items'],payload['action_reason'],
			expected_modified=context['version'],is_waste=payload['is_waste'],comment=payload['comment'],approval_request_only=True)['operation_context']
	if context['action']=='Return':
		return pos.request_pos_return(context['subject'],payload['items'],payload['payments'],payload['action_reason'],
			comment=payload['comment'],approval_request_only=True)['operation_context']
	frappe.throw(_('Unknown operation.'),frappe.PermissionError)


@frappe.whitelist(methods=['POST'])
def request_pos_operation_approval(operation_context, approver, resend=0):
	from rms.api import pos
	pos.require_pos_role()
	from rms.approval_delivery import wants_resend, can_resend, delivery_result, revoke
	resend=wants_resend(resend)
	context=frappe.parse_json(operation_context)
	if not isinstance(context,dict) or context.get('action') not in ACTIONS or not isinstance(context.get('payload'),dict):frappe.throw(_('Choose a valid operation.'))
	context=_rebuild(context)
	if not manager_allowed(approver,context):frappe.throw(_('Choose an authorized manager.'),frappe.PermissionError)
	existing = frappe.db.get_value('Approval Challenge', dict(requester=context['requester'], approver=approver,
		approval_context_hash=digest(context), status=['in', ['Pending', 'Issued']], expires_at=['>', now_datetime()]),
		['name', 'expires_at', 'status', 'creation'], as_dict=True)
	if existing and existing.status == 'Issued':
		if not resend or not can_resend(existing):return delivery_result(existing,approver)
		revoke(existing);existing=None
	doc = frappe.get_doc('Approval Challenge', existing.name, for_update=True) if existing else _new_challenge(context, approver, 'Pending')
	code = _set_issued_code(doc)
	if existing:
		doc.save(ignore_permissions=True)
	else:
		doc.insert(ignore_permissions=True)
	_notify_approval_code(doc, code)
	return delivery_result(doc,approver)


@frappe.whitelist()
def get_pending_pos_operation_approvals(store):
	from rms.api import pos
	pos.require_pos_role();pos.assert_store_access(store)
	if not set(frappe.get_roles()) & {'POS Manager','System Manager'}:frappe.throw(_('Only managers can issue approval codes.'),frappe.PermissionError)
	rows=frappe.get_all('Approval Challenge',filters=dict(store=store,approver=frappe.session.user,status=['in',['Pending','Issued']],action=['in',list(ACTIONS.values())],expires_at=['>',now_datetime()]),
		fields=['name','action','subject_name','requester','operation_payload','expires_at','status'],order_by='creation desc',limit=50)
	return [dict(name=row.name,action=row.action,subject=row.subject_name,requester=row.requester,context=frappe.parse_json(row.operation_payload), status=row.status,
		notification_log=frappe.db.get_value('Notification Log', dict(for_user=frappe.session.user, document_type='Approval Challenge', document_name=row.name), 'name')) for row in rows if manager_allowed(frappe.session.user,frappe.parse_json(row.operation_payload))]


@frappe.whitelist(methods=['POST'])
def issue_pos_operation_approval_code(challenge_name):
	from rms.api import pos
	pos.require_pos_role()
	doc=frappe.get_doc('Approval Challenge',challenge_name,for_update=True)
	if doc.action not in ACTIONS.values() or doc.approver!=frappe.session.user or doc.status!='Pending' or get_datetime(doc.expires_at)<=now_datetime():
		frappe.throw(_('This pending approval is unavailable to you.'),frappe.PermissionError)
	context=frappe.parse_json(doc.operation_payload)
	if not manager_allowed(frappe.session.user,context):frappe.throw(_('Your current POS User permissions do not allow this approval.'),frappe.PermissionError)
	actor=frappe.session.user
	try:
		frappe.set_user(doc.requester)
		current=_rebuild(context)
	finally:frappe.set_user(actor)
	if digest(current)!=doc.approval_context_hash:frappe.throw(_('The operation changed. Ask the cashier to request approval again.'))
	code = _set_issued_code(doc)
	doc.save(ignore_permissions=True)
	_notify_approval_code(doc, code)
	return dict(name=doc.name,code=code,expires_at=str(doc.expires_at))
