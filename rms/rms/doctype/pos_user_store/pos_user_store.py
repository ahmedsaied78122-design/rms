import frappe
from frappe import _
from frappe.model.document import Document


class POSUserStore(Document):
	def validate(self):
		if not getattr(self, "pos_profile", None):
			return
		store = frappe.db.get_value("Store", self.store, ["company", "enabled"], as_dict=True)
		profile = frappe.db.get_value("POS Profile", self.pos_profile, ["company", "disabled"], as_dict=True)
		if not store or not store.enabled:
			frappe.throw(_("Choose an enabled Store before assigning a POS Profile."))
		if not profile or profile.disabled or profile.company != store.company:
			frappe.throw(_("Cashier POS Profile must be enabled and belong to the assigned Store Company."))
