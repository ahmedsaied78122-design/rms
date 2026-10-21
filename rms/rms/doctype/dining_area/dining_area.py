import frappe
from frappe import _
from frappe.model.document import Document


class DiningArea(Document):
	def validate(self):
		if not frappe.db.get_value("Store", self.store, "enabled"):
			frappe.throw(_("Dining Area must belong to an enabled Store."))
		if self.restaurant_brand:
			allowed = frappe.db.exists(
				"Store Brand Assignment",
				{"parent": self.store, "parenttype": "Store", "restaurant_brand": self.restaurant_brand},
			)
			if not allowed:
				frappe.throw(_("The Brand must be assigned to this Store."))
