import frappe
from frappe import _
from frappe.model.document import Document


class OrderType(Document):
	def validate(self):
		if self.sequence_id is not None and self.sequence_id < 0:
			frappe.throw(_("Sequence ID cannot be negative."))

		companies = [row.company for row in self.accounts if row.company]
		if len(companies) != len(set(companies)):
			frappe.throw(_("An Order Type can only have one account mapping per Company."))

		for row in self.accounts:
			self.validate_account(row.company, row.income_account, "Income")
			if row.cost_of_goods_sold_account:
				self.validate_account(row.company, row.cost_of_goods_sold_account, "Expense")

	def validate_account(self, company, account_name, expected_root_type):
		account = frappe.db.get_value(
			"Account", account_name, ["company", "root_type", "is_group"], as_dict=True
		)
		if not account or account.company != company or account.is_group:
			frappe.throw(_("Account {0} must be a ledger account for Company {1}.").format(account_name, company))
		if expected_root_type and account.root_type != expected_root_type:
			frappe.throw(
				_("Account {0} must have Root Type {1}.").format(account_name, expected_root_type)
			)
