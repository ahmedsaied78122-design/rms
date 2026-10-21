import frappe
from frappe import _
from frappe.model.document import Document


class ModifierGroup(Document):
	def validate(self):
		if self.collapsed_by_default and not self.allow_collapse:
			frappe.throw(_("Collapsed By Default requires Allow Collapse."))
