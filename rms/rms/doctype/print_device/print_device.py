import frappe
from frappe import _
from frappe.model.document import Document


class PrintDevice(Document):
	def validate(self):
		if self.print_method == "Network Socket":
			if not self.host or not self.port:
				frappe.throw(_("Network Socket printing requires a Host / IP Address and Port."))
		elif self.print_method == "IPP":
			if not self.ipp_url:
				frappe.throw(_("IPP printing requires an IPP URL."))
		elif self.print_method == "System Queue":
			if not self.queue_name:
				frappe.throw(_("System Queue printing requires a Queue Name."))
		else:
			frappe.throw(_("Choose a supported Print Method."))

		if self.port and not 1 <= self.port <= 65535:
			frappe.throw(_("Port must be between 1 and 65535."))
