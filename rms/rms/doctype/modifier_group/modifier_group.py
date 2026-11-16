import frappe
from frappe import _
from frappe.model.document import Document


class ModifierGroup(Document):
	def validate(self):
		if (self.min_selections or 0) < 0:
			frappe.throw(_("Minimum Selections cannot be negative."))
		if not self.allow_multiple_selections and (self.min_selections or 0) > 1:
			frappe.throw(_("Minimum Selections cannot exceed one for a single-choice group."))
		maximum = self.get("max_selections") or 0
		if maximum < 0:
			frappe.throw(_("Maximum Selections cannot be negative."))
		if not self.allow_multiple_selections and maximum > 1:
			frappe.throw(_("Maximum Selections cannot exceed one for a single-choice group."))
		if maximum and maximum < (self.min_selections or 0):
			frappe.throw(_("Maximum Selections cannot be lower than Minimum Selections."))
		if self.collapsed_by_default and not self.allow_collapse:
			frappe.throw(_("Collapsed By Default requires Allow Collapse."))
