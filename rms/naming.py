"""Editable display names for RMS setup records with stable link identities."""
import frappe
from frappe import _
from frappe.utils import cstr


TITLE_MASTERS = (
	"Dining Area", "Store", "Product Category", "Selling Product", "Restaurant Brand",
	"Dining Table", "Order Type", "Store Menu", "Print Device", "Modifier Group",
	"Preparation Area", "Expense Category",
)


def validate_display_title(doc, method=None):
	doc.title = cstr(doc.title).strip()
	if not doc.title:
		frappe.throw(_("Enter a name."))


def name_from_title(doc, method=None):
	"""Preserve the original creation convention without binding later title edits to name."""
	validate_display_title(doc)
	doc.name = doc.title
