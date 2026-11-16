"""Private, read-only approval summaries for the notification popup."""
import re

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime
from frappe.utils.password import passlibctx


def build_discount_snapshot(order, discount_type, value, reason, scope, guest_check_name=None, preview=None):
	from rms.api import pos
	from rms.pos_rounding import round_pos_payable
	from rms.rms.doctype.pos_order.pos_order import calculate_discount_amount, calculate_order_item_amount
	from rms.snapshots import parse_json_rows
	guest = next((row for row in order.guest_checks or [] if row.name == guest_check_name), None) if guest_check_name else None
	if guest_check_name and not guest:
		frappe.throw(_('The guest check no longer exists.'))
	if guest:
		terms = pos.get_guest_check_discount_totals(order, guest, discount_type, value, reason, scope)
		before = terms['baseline_grand_total']; after = terms['grand_total']
		discount = terms['discount_amount']; taxes_after = terms['final_tax_total']
		subtotal = terms['subtotal']; taxes_before = before - subtotal
	else:
		before_values = order.calculate_tax_preview(return_details=True)
		subtotal = before_values['subtotal']; taxes_before = before_values['tax_total']; before = before_values['grand_total']
		discount = calculate_discount_amount(subtotal, taxes_before, discount_type, value, scope, before)
		terms = frappe._dict(discount_type=discount_type, discount_scope=scope, discount_value=value, discount_amount=discount)
		after_values = order.calculate_tax_preview(apply_discount=True, discount_order=terms, return_details=True)
		after = after_values['grand_total']; taxes_after = after_values['tax_total']
	if preview:
		after = preview['grand_total']; discount = preview['discount_amount']; taxes_after = preview.get('final_tax_total', preview.get('tax_total', taxes_after))
	method = frappe.db.get_value('Restaurant Brand', order.restaurant_brand, 'pos_rounding_method') or 'Nearest'
	currency = frappe.db.get_value('Company', frappe.db.get_value('Store', order.store, 'company'), 'default_currency')
	allocations = pos.get_guest_check_item_allocations(guest) if guest else None
	items=[]
	for row in order.items:
		qty=pos.get_active_order_item_qty(row.qty,row.cancelled_qty)
		if allocations is not None:
			if row.name not in allocations:continue
			if allocations[row.name] is not None:qty=min(qty,flt(allocations[row.name]))
		if qty<=0:continue
		line_total=calculate_order_item_amount(qty,row.selling_price,parse_json_rows(row.modifiers))
		items.append(dict(title=frappe.get_cached_value('Selling Product',row.selling_product,'title') or row.selling_product,
			qty=qty,rate=line_total/qty,amount=line_total,notes=row.notes or '',
			modifiers=[frappe.get_cached_value('Selling Product',entry.modifier_product,'title') or entry.modifier_product for entry in parse_json_rows(row.modifiers)]))
	cashier=frappe.db.get_value('Cashier Session',order.cashier_session,'user')
	limit=frappe.db.get_value('POS User',{'user':cashier,'enabled':1},'max_manual_discount_percent') if cashier else None
	return dict(discount_type=discount_type, discount_value=flt(value), discount_scope=scope, comment=reason,
		currency=currency, subtotal=flt(subtotal), total_before=flt(before), total_after=flt(after), discount_amount=flt(discount),
		payable_before=float(round_pos_payable(before, method)), payable_after=float(round_pos_payable(after, method)),
		taxes_before=flt(taxes_before), taxes_after=flt(taxes_after), rounding_method=method,
		order_modified=str(order.modified), customer=order.customer, brand=order.restaurant_brand, order_type=order.order_type,
		table=order.dining_table, guest_check_name=guest_check_name, items=items, requester_limit_percent=limit)


@frappe.whitelist()
def get_approval_details(challenge_name=None, notification_name=None):
	from rms.api import pos
	pos.require_pos_role()
	if notification_name:
		notice=frappe.get_doc('Notification Log',notification_name)
		if notice.for_user != frappe.session.user or notice.document_type != 'Approval Challenge':
			frappe.throw(_('This approval notification is not addressed to you.'),frappe.PermissionError)
		if challenge_name and challenge_name != notice.document_name:
			frappe.throw(_('Notification does not match this approval.'),frappe.PermissionError)
		challenge_name=notice.document_name
	doc=frappe.get_doc('Approval Challenge',challenge_name)
	if doc.approver != frappe.session.user:
		frappe.throw(_('Only the selected approver can view this approval code.'),frappe.PermissionError)
	doc.check_permission('read')
	context=frappe.parse_json(doc.operation_payload or '{}')
	payload=context.get('payload') or {}
	is_snapshot=bool(payload.get('currency') and 'total_before' in payload)
	if doc.action == pos.POS_DISCOUNT_APPROVAL_ACTION and not is_snapshot and payload.get('discount_type'):
		order=frappe.get_doc('POS Order',doc.subject_name)
		payload={**payload,**build_discount_snapshot(order,payload['discount_type'],payload['discount_value'],payload.get('comment',''),payload.get('discount_scope','Net Total'),payload.get('guest_check_name'))}
	elif doc.action == 'Post Shift Expense':
		expense=frappe.get_doc('Shift Expense',doc.subject_name)
		payload=dict(amount=expense.amount,currency=expense.currency,comment=expense.remarks,category=expense.expense_category,mode_of_payment=expense.mode_of_payment,items=[])
	if payload.get('action_reason'):
		payload['reason']=frappe.db.get_value('POS Action Reason',payload['action_reason'],'reason') or payload['action_reason']
	if not payload.get('currency'):
		payload['currency']=frappe.db.get_value('Company',frappe.db.get_value('Store',doc.store,'company'),'default_currency')
	if doc.action=='POS Return':payload['amount']=sum(flt(row.get('amount')) for row in payload.get('payments',[]))
	changed=False
	if doc.action==pos.POS_DISCOUNT_APPROVAL_ACTION and payload.get('order_modified'):
		current_modified=frappe.db.get_value('POS Order',doc.subject_name,'modified')
		changed=bool(current_modified and (get_datetime(current_modified)!=get_datetime(payload['order_modified']) if is_snapshot else get_datetime(current_modified)>get_datetime(doc.creation)))
	expired=not doc.expires_at or get_datetime(doc.expires_at)<=now_datetime()
	code=None
	if doc.status=='Issued' and not expired and not changed:
		logs=frappe.get_all('Notification Log',filters=dict(for_user=doc.approver,document_type='Approval Challenge',document_name=doc.name),fields=['name','subject','title'],order_by='creation desc',limit=5)
		for row in logs:
			for candidate in re.findall(r'(?<!\d)\d{6}(?!\d)',(row.title or '')+' '+(row.subject or '')):
				if doc.code_hash and passlibctx.verify(candidate,doc.code_hash):
					code=candidate;break
			if code:break
	if notification_name:
		frappe.db.set_value('Notification Log',notification_name,'read',1,update_modified=False)
	return dict(name=doc.name,action=doc.action,subject=doc.subject_name,subject_doctype=doc.subject_doctype,
		store=doc.store,requester=doc.requester,requester_name=frappe.db.get_value('User',doc.requester,'full_name') or doc.requester,
		created_at=str(doc.creation),expires_at=str(doc.expires_at),status=('Expired' if expired else 'Changed' if changed else doc.status) if doc.status=='Issued' else doc.status,
		code=code,payload=payload,historical_snapshot=is_snapshot, remaining_seconds=max(0,int((get_datetime(doc.expires_at)-now_datetime()).total_seconds())) if doc.expires_at else 0)
