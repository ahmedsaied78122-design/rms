from frappe.model.document import Document

from rms.streaming import SYNC_SCHEMA_VERSION


class RMSSyncSettings(Document):
	def validate(self):
		self.schema_version = SYNC_SCHEMA_VERSION
