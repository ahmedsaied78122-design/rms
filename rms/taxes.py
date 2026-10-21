from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate


def validate_rms_cashier_session_pos_opening_entry(invoice, session, user):
	"""Validate the open POS register linked to the active RMS cashier session.

	ERPNext normally requires the opening entry to start today. An RMS cashier
	session can intentionally remain open across midnight, so keep ERPNext's
	profile-level uniqueness and register ownership checks while allowing that
	linked open session to span calendar dates.
	"""
	if (session.status != "Open" or session.user != user or not session.pos_opening_entry
			or session.pos_profile != invoice.pos_profile):
		frappe.throw(_("The POS Opening Entry must match the active Cashier Session."))

	opening_entries = frappe.get_all(
		"POS Opening Entry",
		filters={"pos_profile": invoice.pos_profile, "status": "Open", "docstatus": 1},
		fields=["name", "period_start_date", "pos_profile", "user", "company", "status", "docstatus"],
		limit_page_length=2,
	)
	if not opening_entries:
		frappe.throw(
			title=_("POS Opening Entry Missing"),
			msg=_("No open POS Opening Entry found for POS Profile {0}.").format(frappe.bold(invoice.pos_profile)),
		)
	if len(opening_entries) > 1:
		frappe.throw(
			title=_("Multiple POS Opening Entry"),
			msg=_("POS Profile - {0} has multiple open POS Opening Entries. Please close or cancel the existing entries before proceeding.").format(invoice.pos_profile),
		)

	opening = opening_entries[0]
	if (opening.name != session.pos_opening_entry or opening.pos_profile != invoice.pos_profile
			or opening.user != user or opening.company != invoice.company or opening.status != "Open"
			or opening.docstatus != 1):
		frappe.throw(_("The POS Opening Entry must match the active Cashier Session."))
	if getdate(opening.period_start_date) > getdate(nowdate()):
		frappe.throw(_("The POS Opening Entry period cannot start in the future."))


@contextmanager
def allow_rms_cashier_session_pos_invoice(invoice, session, user):
	"""Use RMS session-aware opening validation only for this POS Invoice instance."""
	original_validator = invoice.validate_pos_opening_entry
	invoice.validate_pos_opening_entry = lambda: validate_rms_cashier_session_pos_opening_entry(
		invoice, session, user
	)
	try:
		yield
	finally:
		invoice.validate_pos_opening_entry = original_validator


@contextmanager
def prevent_pos_item_price_autoinsert(invoice):
	"""Load invoice defaults without ERPNext auto-inserting Item Prices for POS rates.

	RMS order rows already carry validated item, UOM, warehouse, and selling rates.
	ERPNext's generic item-detail lookup can create a Price List Item Price as a
	read-side effect, which is incorrect for Store/Brand/Order Type-specific RMS
	prices and can overwrite the standard selling list with a contextual rate.
	"""
	set_item_details = invoice.set_missing_item_details
	invoice.set_missing_item_details = lambda *args, **kwargs: None
	try:
		yield
	finally:
		invoice.set_missing_item_details = set_item_details


def apply_order_tax_template(invoice, tax_template):
	"""Replace any POS Profile tax rows with the Store + Order Type template."""
	invoice.taxes_and_charges = tax_template
	invoice.set("taxes", [])
	if tax_template:
		invoice.set_taxes()


def apply_order_discount(invoice, order):
	"""Apply RMS discount fields after POS Profile defaults have been loaded."""
	invoice.apply_discount_on = order.discount_scope
	invoice.discount_amount = 0
	invoice.additional_discount_percentage = 0
	if flt(order.discount_amount) > 0:
		if order.discount_type == "Percentage":
			invoice.additional_discount_percentage = flt(order.discount_value)
		else:
			invoice.discount_amount = flt(order.discount_amount)
