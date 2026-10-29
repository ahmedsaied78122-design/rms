import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class ShiftExpense(Document):
	def validate(self):
		if not self.flags.from_pos_api and not self.is_new() and self._action != "submit":
			frappe.throw(_("Shift Expenses are changed through the POS workflow."))
		if flt(self.amount) <= 0:
			frappe.throw(_("Enter an expense amount greater than zero."))
		if self.status not in ("Draft", "Pending Approval", "Posted", "Rejected"):
			frappe.throw(_("Invalid Shift Expense status."))

	def on_update(self):
		if not self.flags.from_pos_api and self._action != "submit" and self.status != "Draft":
			frappe.throw(_("Shift Expense status is controlled by the POS workflow."))

	def before_submit(self):
		if self.status != "Posted" or not self.journal_entry:
			frappe.throw(_("A Shift Expense can only be submitted after its Journal Entry is posted."))
		if frappe.db.get_value("Journal Entry", self.journal_entry, "docstatus") != 1:
			frappe.throw(_("Submit the linked Journal Entry before submitting this Shift Expense."))

	def post_to_ledger(self, approved_by):
		if self.status == "Posted" and self.journal_entry:
			if self.docstatus == 0 and frappe.db.get_value("Journal Entry", self.journal_entry, "docstatus") == 1:
				self.flags.ignore_permissions = True
				self.submit()
			return self.journal_entry
		if self.status not in ("Draft", "Pending Approval"):
			frappe.throw(_("Only an unposted Shift Expense can be approved."))
		if not self.journal_entry:
			journal_entry = frappe.new_doc("Journal Entry")
			journal_entry.voucher_type = "Journal Entry"
			journal_entry.company = self.company
			journal_entry.posting_date = self.business_date
			journal_entry.user_remark = _("POS expense {0}: {1}").format(self.name, self.remarks or self.expense_category)
			journal_entry.append("accounts", {
				"account": self.expense_account,
				"debit_in_account_currency": flt(self.amount),
				"cost_center": self.cost_center,
			})
			journal_entry.append("accounts", {
				"account": self.payment_account,
				"credit_in_account_currency": flt(self.amount),
			})
			journal_entry.insert(ignore_permissions=True)
			self.journal_entry = journal_entry.name
			self.status = "Pending Approval"
			self.flags.from_pos_api = True
			self.save(ignore_permissions=True)
		journal_entry = frappe.get_doc("Journal Entry", self.journal_entry)
		if journal_entry.docstatus == 0:
			journal_entry.flags.ignore_permissions = True
			journal_entry.submit()
		self.status = "Posted"
		self.approver = approved_by
		self.approved_at = frappe.utils.now_datetime()
		self.flags.from_pos_api = True
		self.flags.ignore_permissions = True
		self.submit()
		session = frappe.get_doc("Cashier Session", self.cashier_session)
		session.reload()
		if session.status != "Open":
			frappe.throw(_("The expense was posted after the Cashier Session stopped accepting expenses."))
		session.save(ignore_permissions=True)
		return self.journal_entry
