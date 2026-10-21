import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from rms.streaming import SYNC_SCHEMA, SYNC_SCHEMA_VERSION


class RMSSyncEvent(Document):
	def before_insert(self):
		self.captured_at = self.captured_at or now_datetime()

	def validate(self):
		if not self.is_new():
			frappe.throw(_("RMS Sync Events are immutable."), frappe.PermissionError)
		if not self.flags.from_streaming_capture:
			frappe.throw(_("RMS Sync Events are created only by local capture."), frappe.PermissionError)
		if self.source_doctype not in SYNC_SCHEMA:
			frappe.throw(_("This source type is not on the RMS sync allowlist."))
		if self.schema_version != SYNC_SCHEMA_VERSION:
			frappe.throw(_("The event payload schema version is not supported."))
		if not self.idempotency_key or not self.payload_hash or not self.payload:
			frappe.throw(_("The sync event identity and verified payload are required."))

	def on_trash(self):
		frappe.throw(_("RMS Sync Events cannot be deleted."), frappe.PermissionError)
