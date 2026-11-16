"""Shared resend policy for POS approval codes."""
from datetime import datetime

import frappe
from frappe.utils import get_datetime, now_datetime

RESEND_SECONDS = 60


def wants_resend(value):
	if value not in (None,False,True,0,1,'0','1'):
		frappe.throw('Choose a valid resend option.')
	return value in (True,1,'1')


def delivery_result(doc, approver):
	created=getattr(doc,'creation',None)
	if not isinstance(created,(str,datetime)):created=None
	elapsed=max(0,(now_datetime()-get_datetime(created)).total_seconds()) if created else 0
	expires=getattr(doc,'expires_at',None)
	if not isinstance(expires,(str,datetime)):expires=None
	return dict(name=doc.name,expires_at=str(expires),delivered_to=approver,
		expires_in_seconds=max(0,int((get_datetime(expires)-now_datetime()).total_seconds())) if expires else 300,
		resend_after_seconds=max(0,int(RESEND_SECONDS-elapsed+0.999)))


def can_resend(doc):
	return delivery_result(doc,'')['resend_after_seconds']==0


def revoke(doc):
	frappe.db.set_value('Approval Challenge',doc.name,'status','Revoked')
