import frappe
from frappe import _
from frappe.model.document import Document


class Store(Document):
	def validate(self):
		self.validate_brands()
		self.validate_defaults()
		self.validate_order_type_taxes()

	def validate_brands(self):
		brands = [row.restaurant_brand for row in self.brands if row.restaurant_brand]
		if len(brands) != len(set(brands)):
			frappe.throw(_("A brand can only be added once to a Store."))

		defaults = [row for row in self.brands if row.is_default]
		if len(defaults) != 1:
			frappe.throw(_("Select exactly one default Brand for this Store."))

		for brand in brands:
			if not frappe.db.get_value("Restaurant Brand", brand, "enabled"):
				frappe.throw(_("Brand {0} is disabled.").format(frappe.bold(brand)))

	def validate_defaults(self):
		if self.default_warehouse and self.company:
			warehouse = frappe.db.get_value(
				"Warehouse", self.default_warehouse, ["company", "is_group", "disabled"], as_dict=True
			)
			if not warehouse or warehouse.company != self.company or warehouse.is_group or warehouse.disabled:
				frappe.throw(_("Default Warehouse must be an enabled leaf Warehouse belonging to the selected Company."))

		if self.default_preparation_area:
			area = frappe.db.get_value(
				"Preparation Area", self.default_preparation_area, ["store", "enabled"], as_dict=True
			)
			if not area or area.store != self.name or not area.enabled:
				frappe.throw(_("Default Preparation Area must belong to this Store."))

		if self.pos_profile:
			profile_company = frappe.db.get_value("POS Profile", self.pos_profile, "company")
			profile_disabled = frappe.db.get_value("POS Profile", self.pos_profile, "disabled")
			if profile_company != self.company or profile_disabled:
				frappe.throw(_("POS Profile must be enabled and belong to the Store Company."))

	def validate_order_type_taxes(self):
		seen = set()
		for row in self.order_type_taxes:
			if row.order_type in seen:
				frappe.throw(_("Each Order Type can have only one tax template per Store."))
			seen.add(row.order_type)

			if not frappe.db.get_value("Order Type", row.order_type, "enabled"):
				frappe.throw(_("Order Type {0} is disabled.").format(frappe.bold(row.order_type)))

			template_company = frappe.db.get_value(
				"Sales Taxes and Charges Template", row.sales_taxes_and_charges_template, "company"
			)
			if self.company and template_company != self.company:
				frappe.throw(_("The Sales Taxes and Charges Template must belong to the Store Company."))
