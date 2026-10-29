import frappe
from frappe import _
from frappe.model.document import Document


class POSActionReason(Document):
	def validate(self):
		self.reason = (self.reason or "").strip()
		if not self.reason:
			frappe.throw(_("Enter a reason."))


def validate_pos_action_reason(reason_name, action):
	if not reason_name:
		frappe.throw(_("Select a reason."))
	reason = frappe.get_doc("POS Action Reason", reason_name)
	if not reason.enabled:
		frappe.throw(_("This POS action reason is disabled."))
	if reason.applies_to not in ("Both", action):
		frappe.throw(_("This reason is not available for {0}.").format(_(action.lower())))
	return reason.reason
