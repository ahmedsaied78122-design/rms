import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class PrintDispatchJob(Document):
	def before_insert(self):
		self.status = "Queued"
		self.attempt_count = 0
		self.queued_at = self.queued_at or now_datetime()

	def validate(self):
		if not self.idempotency_key:
			frappe.throw(_("Print Dispatch Job requires an Idempotency Key."))
		device = frappe.db.get_value(
			"Print Device", self.print_device, ["enabled", "print_method"], as_dict=True
		)
		if not device or not device.enabled:
			frappe.throw(_("Choose an enabled Print Device."))
		if self.preparation_area:
			area_store = frappe.db.get_value("Preparation Area", self.preparation_area, "store")
			if area_store != self.store:
				frappe.throw(_("Preparation Area must belong to the Print Job Store."))
		if not self.document_type or not self.document_name:
			frappe.throw(_("Print Job needs a source document."))

	def after_insert(self):
		frappe.enqueue(
			"rms.api.printing.process_print_job",
			queue="short",
			job_name=f"rms-print-{self.name}",
			enqueue_after_commit=True,
			print_job_name=self.name,
		)

	def retry(self):
		if self.status not in ("Failed", "Cancelled"):
			frappe.throw(_("Only a failed or cancelled Print Job can be retried."))
		self.status = "Queued"
		self.last_error = None
		self.queued_at = now_datetime()
		self.save(ignore_permissions=True)
		frappe.enqueue(
			"rms.api.printing.process_print_job",
			queue="short",
			job_name=f"rms-print-{self.name}-retry-{self.attempt_count + 1}",
			enqueue_after_commit=True,
			print_job_name=self.name,
		)
