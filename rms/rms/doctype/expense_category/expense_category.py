import frappe
from frappe import _
from frappe.model.document import Document


class ExpenseCategory(Document):
	def validate(self):
		account = frappe.db.get_value("Account", self.expense_account,
			["company", "root_type", "is_group", "account_currency"], as_dict=True)
		if (not account or account.company != self.company or account.root_type != "Expense" or account.is_group):
			frappe.throw(_("Choose a non-group Expense Account from the selected Company."))
		company_currency = frappe.db.get_value("Company", self.company, "default_currency")
		if account.account_currency != company_currency:
			frappe.throw(_("Expense Account must use the Company currency."))
		if self.cost_center:
			cost_center = frappe.db.get_value("Cost Center", self.cost_center,
				["company", "is_group"], as_dict=True)
			if not cost_center or cost_center.company != self.company or cost_center.is_group:
				frappe.throw(_("Choose a non-group Cost Center from the selected Company."))
