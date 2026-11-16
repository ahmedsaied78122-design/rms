"""Validate authenticated upstream RMS snapshots without replaying POS actions.

The transport still runs Frappe permissions, mandatory/link/select validation and
native ERP controllers. These checks replace only source-side POS workflow
transitions during a server-owned Master replay; posted flags grant no authority.
"""

import math
from collections import Counter

import frappe
from frappe import _
from frappe.utils import flt

from rms.snapshots import parse_json_rows


def upstream(doc):
	from arab_streaming.streaming.context import replay_source
	from rms.streaming_policy import RMS_OPERATIONS

	return bool(
		doc.doctype in RMS_OPERATIONS
		and frappe.conf.get("arab_streaming_site_role") == "Master"
		and replay_source()
	)


def require(condition, message):
	if not condition:
		frappe.throw(_(message))


def number(value, positive=False):
	value = flt(value)
	require(
		math.isfinite(value) and (not positive or value > 0),
		"Invalid numeric value in streaming snapshot.",
	)
	return value


def linked(doctype, name):
	require(bool(name), "A required streaming reference is missing.")
	return frappe.get_doc(doctype, name)


def same(value, expected):
	require(
		value == expected,
		"Streaming snapshot references inconsistent business records.",
	)


def money(value, expected):
	require(
		abs(number(value) - number(expected)) <= 0.01,
		"Streaming snapshot amounts do not reconcile.",
	)


def validate(doc):
	require(
		upstream(doc), "Only authenticated upstream streaming can apply an RMS replica."
	)
	store = linked("Store", doc.store)
	previous = doc.get_doc_before_save()
	if previous:
		same(doc.store, previous.store)
	if doc.get("company"):
		same(doc.company, store.company)
	if doc.get("cashier_session"):
		session = linked("Cashier Session", doc.cashier_session)
		same(session.store, doc.store)
	if doc.doctype == "Cashier Session":
		validate_session(doc, store)
	elif doc.doctype == "POS Order":
		validate_order(doc, store)
	elif doc.doctype == "Kitchen Ticket":
		order = linked("POS Order", doc.pos_order)
		same(order.store, doc.store)
		area = linked("Preparation Area", doc.preparation_area)
		same(area.store, doc.store)
		doc.validate_items()
	elif doc.doctype == "Shift Expense":
		number(doc.amount, positive=True)
		if doc.status == "Posted":
			journal = linked("Journal Entry", doc.journal_entry)
			same(journal.company, store.company)
			same(journal.docstatus, 1)
			money(journal.total_debit, doc.amount)
	elif doc.doctype == "POS Return":
		validate_return(doc, store)
	elif doc.doctype == "Waste Entry":
		validate_waste(doc, store)


def validate_session(doc, store):
	profile = linked("POS Profile", doc.pos_profile)
	same(profile.company, store.company)
	opening = linked("POS Opening Entry", doc.pos_opening_entry)
	same(opening.company, store.company)
	same(opening.pos_profile, doc.pos_profile)
	same(opening.user, doc.user)
	require(
		bool(doc.opened_at and doc.business_date),
		"The original session dates are required.",
	)
	require(bool(doc.payments), "The session payment snapshot is required.")
	seen = set()
	for row in doc.payments:
		require(
			row.mode_of_payment not in seen,
			"Duplicate payment method in streaming snapshot.",
		)
		seen.add(row.mode_of_payment)
		for field in (
			"opening_amount",
			"expected_amount",
			"actual_amount",
			"difference",
		):
			number(row.get(field))
		if doc.status in ("Closing", "Closed"):
			money(row.difference, flt(row.actual_amount) - flt(row.expected_amount))
	if doc.status == "Closed":
		closing = linked("POS Closing Entry", doc.pos_closing_entry)
		same(closing.pos_opening_entry, doc.pos_opening_entry)
		same(closing.docstatus, 1)
		same(closing.status, "Submitted")
		same(opening.status, "Closed")
		require(bool(doc.closed_at), "The original session closing date is required.")
	previous = doc.get_doc_before_save()
	if previous:
		for field in ("user", "pos_profile", "pos_opening_entry"):
			same(doc.get(field), previous.get(field))
		if previous.status == "Closed":
			same(doc.status, "Closed")


def validate_order(doc, store):
	require(
		bool(doc.items and doc.business_date),
		"The order snapshot must include items and its business date.",
	)
	for row in doc.items:
		qty = number(row.qty, positive=True)
		cancelled = number(row.cancelled_qty)
		require(
			0 <= cancelled <= qty, "Cancelled quantities exceed the order quantity."
		)
		product = linked("Selling Product", row.selling_product)
		same(product.item, row.item)
		number(row.selling_price)
		number(row.amount)
		for field in ("modifiers", "recipe_snapshot"):
			for saved in parse_json_rows(row.get(field)):
				number(saved.get("qty"), positive=True)
				if saved.get("warehouse"):
					same(linked("Warehouse", saved.warehouse).company, store.company)
		if row.warehouse:
			same(linked("Warehouse", row.warehouse).company, store.company)
	for field in ("subtotal", "discount_amount", "tax_total", "grand_total"):
		number(doc.get(field))
	if doc.status == "Paid":
		invoices = {
			row.pos_invoice
			for row in doc.guest_checks
			if row.status == "Paid" and row.pos_invoice
		}
		invoices = invoices or {doc.pos_invoice}
		for name in invoices:
			invoice = linked("POS Invoice", name)
			same(invoice.company, store.company)
			same(invoice.docstatus, 1)
			same(invoice.customer, doc.customer)
		doc.validate_payment_state()
		doc.validate_terminal_state()
	previous = doc.get_doc_before_save()
	if previous and previous.status in ("Paid", "Cancelled"):
		same(doc.status, previous.status)


def validate_return(doc, store):
	source = linked("POS Invoice", doc.source_pos_invoice)
	same(source.company, store.company)
	same(source.is_return, 0)
	same(source.docstatus, 1)
	same(source.customer, doc.customer)
	source_items = {row.name: row for row in source.items}
	seen = set()
	require(
		bool(doc.items and doc.payments),
		"Return items and refund payments are required.",
	)
	for row in doc.items:
		require(
			row.source_pos_invoice_item in source_items
			and row.source_pos_invoice_item not in seen,
			"Each returned line must belong to the source invoice exactly once.",
		)
		seen.add(row.source_pos_invoice_item)
		original = source_items[row.source_pos_invoice_item]
		same(row.item_code, original.item_code)
		require(
			number(row.qty, positive=True) <= flt(original.qty),
			"Returned quantity exceeds the sold quantity.",
		)
		money(row.rate, original.rate)
	for row in doc.payments:
		number(row.amount, positive=True)
	money(sum(flt(row.amount) for row in doc.payments), doc.refund_total)
	if doc.status == "Approved":
		credit = linked("POS Invoice", doc.return_pos_invoice)
		same(credit.docstatus, 1)
		same(credit.is_return, 1)
		same(credit.return_against, source.name)
		money(abs(flt(credit.rounded_total)), doc.refund_total)
		requested = Counter(
			{row.source_pos_invoice_item: flt(row.qty) for row in doc.items}
		)
		actual = Counter()
		for row in credit.items:
			actual[row.pos_invoice_item] += abs(flt(row.qty))
		same(actual, requested)


def cancel_waste(doc):
	"""Cancel the existing movement while the native parent is already cancelled.

	The child's earlier Cancel event can be blocked by this still-active parent.
	Native parent cancellation stores docstatus=2 before on_cancel, so cancelling
	the validated child here follows the same atomic order as the source.
	"""
	require(upstream(doc) and doc.docstatus == 2, "Only an upstream waste cancellation is allowed.")
	stock = linked("Stock Entry", doc.stock_entry)
	if stock.docstatus == 1:
		validate_waste(doc, linked("Store", doc.store), stock_status=1)
		stock.cancel()  # Normal permissions, backlinks, stock and accounting reversal.
	validate(doc)


def validate_waste(doc, store, stock_status=None):
	number(doc.quantity, positive=True)
	require(bool(doc.items), "The original waste component snapshot is required.")
	for row in doc.items:
		number(row.qty, positive=True)
		same(linked("Warehouse", row.warehouse).company, store.company)
		money(row.amount, flt(row.qty) * number(row.basic_rate))
	desired = doc.flags.get("streaming_target_docstatus", doc.docstatus)
	if desired in (1, 2):
		stock = linked("Stock Entry", doc.stock_entry)
		same(stock.company, store.company)
		same(stock.docstatus, desired if stock_status is None else stock_status)
		same(stock.purpose, "Material Issue")
		expected, actual = Counter(), Counter()
		for row in doc.items:
			expected[(row.item, row.warehouse)] += flt(row.qty)
		for row in stock.items:
			actual[(row.item_code, row.s_warehouse)] += flt(row.transfer_qty)
		require(
			expected.keys() == actual.keys(),
			"Waste components do not match the original stock movement.",
		)
		for key, qty in expected.items():
			require(
				abs(qty - actual[key]) < 0.000001,
				"Waste quantities do not match the original stock movement.",
			)
		same(doc.status, "Submitted" if desired == 1 else "Cancelled")
