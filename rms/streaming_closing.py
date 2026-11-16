"""Receive a completed POS closing without consolidating its invoices twice."""

import frappe
from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import POSClosingEntry

from rms.streaming_replica import linked, same, require


def upstream_closing(doc):
	from arab_streaming.streaming.context import replay_source

	return bool(
		doc.doctype == "POS Closing Entry"
		and frappe.conf.get("arab_streaming_site_role") == "Master"
		and replay_source()
	)


class RMSPOSClosingEntry(POSClosingEntry):
	def before_update_after_submit(self):
		if upstream_closing(self):
			self.validate_replica()

	def validate_replica(self):
		opening = linked("POS Opening Entry", self.pos_opening_entry)
		for key in ("company", "pos_profile", "user"):
			same(self.get(key), opening.get(key))
		require(
			self.status in ("Submitted", "Cancelled"),
			"Only a completed POS closing can be replicated.",
		)
		self.validate_duplicate_pos_invoices()
		for row in self.pos_transactions:
			invoice = linked("POS Invoice", row.pos_invoice)
			same(invoice.company, self.company)
			same(invoice.pos_profile, self.pos_profile)
			same(invoice.docstatus, 1)
			# Consolidation already ran on the owning branch. Its Sales Invoice
			# is transferred through the native financial controller separately.
			if self.status == "Submitted":
				merged = linked("Sales Invoice", invoice.consolidated_invoice)
				same(merged.company, self.company)
				same(merged.docstatus, 1)
				require(
					any(item.pos_invoice == invoice.name for item in merged.items),
					"The consolidated Sales Invoice does not contain this POS Invoice.",
				)

	def validate(self):
		if upstream_closing(self):
			self.validate_replica()
		else:
			super().validate()

	def on_submit(self):
		if upstream_closing(self):
			self.validate_replica()
		else:
			super().on_submit()

	def on_cancel(self):
		if upstream_closing(self):
			self.validate_replica()
		else:
			super().on_cancel()


def capture_native_change(doc, method=None):
	"""Native consolidation uses db_set: capture its committed business state."""
	# Arab Streaming 0.2.9 owns native db_set changes. Ordinary ORM lifecycle
	# callbacks are already captured by its on_update/on_submit/on_cancel hooks.
	if getattr(doc, "_arab_streaming_dbset_before", None) is not None or getattr(doc, "_action", None) in (
		"save", "submit", "cancel", "update_after_submit"
	):
		return
	if doc.docstatus and doc.doctype in ("POS Closing Entry", "POS Invoice"):
		from arab_streaming.streaming.outbox import capture

		capture(doc, "on_cancel" if doc.docstatus == 2 else "on_update_after_submit")


def preserve_invoice_rounding(doc, method=None):
	from arab_streaming.streaming.context import replay_source
	from rms.pos_rounding import round_pos_payable
	from frappe.utils import flt

	if not (
		replay_source()
		and frappe.conf.get("arab_streaming_site_role") == "Master"
		and doc.flags.get("streaming_target_docstatus")
	):
		return
	# Preserve the source payable even if the Brand rounding choice changed
	# after this historical invoice was posted. Never trust a posted flag alone.
	for choice in ("No Rounding", "Nearest", "Round Up", "Round Down"):
		if (
			abs(
				flt(round_pos_payable(doc.grand_total, choice)) - flt(doc.rounded_total)
			)
			< 0.005
		):
			doc.flags.rms_pos_rounding_method = choice
			return
	require(
		False,
		"The replicated invoice payable does not match a supported rounding rule.",
	)
