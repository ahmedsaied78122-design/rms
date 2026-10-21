import frappe
from frappe import _
from frappe.model.document import Document


class PreparationArea(Document):
	def validate(self):
		if self.has_printer and not self.print_device:
			frappe.throw(_("Select a Print Device when Has Printer is enabled."))
		if not self.has_printer:
			self.print_device = None
		if self.print_device and not frappe.db.get_value("Print Device", self.print_device, "enabled"):
			frappe.throw(_("The selected Print Device is disabled."))
		if self.store and not frappe.db.get_value("Store", self.store, "enabled"):
			frappe.throw(_("Preparation Area must belong to an enabled Store."))
