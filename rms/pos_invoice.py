"""POS Invoice controller compatibility for Frappe 15."""

from erpnext.accounts.doctype.pos_invoice.pos_invoice import POSInvoice

from rms.pos_rounding import POSInvoiceRoundingMixin


class RMSPOSInvoice(POSInvoiceRoundingMixin, POSInvoice):
	pass
