import frappe
from frappe import _
from frappe.model.document import Document


class DiningTable(Document):
	def validate(self):
		area_store = frappe.db.get_value("Dining Area", self.dining_area, "store")
		if area_store != self.store:
			frappe.throw(_("Dining Area must belong to the selected Store."))
		if self.capacity is not None and self.capacity < 1:
			frappe.throw(_("Capacity must be at least one person."))
		if self.store and not frappe.db.get_value("Store", self.store, "enabled"):
			frappe.throw(_("Dining Table must belong to an enabled Store."))
