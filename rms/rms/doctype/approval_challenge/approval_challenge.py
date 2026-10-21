import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime
from frappe.utils.password import passlibctx


MAX_FAILED_ATTEMPTS = 5


class ApprovalChallenge(Document):
	def validate(self):
		if not self.flags.from_pos_api and self.is_new():
			frappe.throw(_("Approval Challenges are created by an approved POS workflow."))

	def verify_code(self, code, consume=True):
		if self.status != "Issued":
			frappe.throw(_("This approval code has already been used or revoked."))
		if not self.expires_at or get_datetime(self.expires_at) <= now_datetime():
			self.status = "Expired"
			self.flags.from_pos_api = True
			self.save(ignore_permissions=True)
			frappe.db.commit()
			frappe.throw(_("This approval code has expired."))
		if self.failed_attempts >= MAX_FAILED_ATTEMPTS:
			self.status = "Revoked"
			self.flags.from_pos_api = True
			self.save(ignore_permissions=True)
			frappe.db.commit()
			frappe.throw(_("This approval code was locked after too many attempts."))
		if not self.code_hash or not passlibctx.verify(str(code), self.code_hash):
			self.failed_attempts += 1
			if self.failed_attempts >= MAX_FAILED_ATTEMPTS:
				self.status = "Revoked"
			self.flags.from_pos_api = True
			self.save(ignore_permissions=True)
			frappe.db.commit()
			if self.status == "Revoked":
				frappe.throw(_("This approval code was locked after too many attempts."))
			frappe.throw(_("The approval code is incorrect."))
		if consume:
			self.status = "Consumed"
			self.used_at = now_datetime()
			self.flags.from_pos_api = True
			self.save(ignore_permissions=True)
		return True
