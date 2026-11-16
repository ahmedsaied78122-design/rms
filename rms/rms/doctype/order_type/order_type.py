import frappe
from frappe import _
from frappe.model.document import Document


class OrderType(Document):
	def after_rename(self, old, new, merge=False):
		# Generated selling price-list identities include the Order Type ID.
		# Rename those records too, so Item Prices and invoice links keep their rates.
		rules = frappe.get_all("Selling Product Price Rule", filters={"order_type": new},
			fields=["parent", "store", "restaurant_brand"])
		products = {}
		price_lists = {}
		for row in rules:
			if row.parent not in products:
				products[row.parent] = frappe.get_doc("Selling Product", row.parent)
			product = products[row.parent]
			conditions = {"store": row.store or "", "order_type": new, "restaurant_brand": row.restaurant_brand or ""}
			for currency in product.get_price_currencies(row.store):
				old_list = product.get_price_list_name({**conditions, "order_type": old}, currency)
				new_list = product.get_price_list_name(conditions, currency)
				if old_list != new_list and frappe.db.exists("Price List", old_list):
					price_lists[old_list] = new_list
		for old_list, new_list in price_lists.items():
			if frappe.db.exists("Price List", new_list):
				frappe.throw(_("Price List {0} already exists. Resolve the duplicate before renaming this Order Type.").format(new_list))
			frappe.rename_doc("Price List", old_list, new_list, show_alert=False, rebuild_search=False)
		if price_lists:
			frappe.enqueue("frappe.utils.global_search.rebuild_for_doctype", doctype="Price List", enqueue_after_commit=True)

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
