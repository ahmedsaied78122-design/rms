import frappe
from frappe import _
from frappe.model.document import Document


class POSUser(Document):
	def validate(self):
		self.validate_user()
		self.validate_employee()
		self.validate_stores()
		self.validate_permissions()
		self.validate_scopes()

	def validate_permissions(self):
		max_discount = frappe.utils.flt(self.max_manual_discount_percent or 0)
		if max_discount < 0 or max_discount > 100:
			frappe.throw(_("Maximum manual discount must be between 0% and 100%."))
		self.roles_summary = ", ".join(sorted(set(frappe.get_roles(self.user))))

	def validate_scopes(self):
		stores = {row.store for row in self.stores}
		self.validate_scope_table(
			"allowed_brands", "restaurant_brand", "Restaurant Brand",
			"Store Brand Assignment", "restaurant_brand", stores,
		)
		self.validate_scope_table(
			"allowed_order_types", "order_type", "Order Type",
			"Store Order Type Tax", "order_type", stores,
		)
		self.validate_scope_table(
			"allowed_preparation_areas", "preparation_area", "Preparation Area",
			"Preparation Area", "name", stores,
		)

	def validate_scope_table(self, table_field, link_field, doctype, source_doctype, source_field, stores):
		rows = self.get(table_field) or []
		selected = [row.get(link_field) for row in rows]
		if len(selected) != len(set(selected)):
			frappe.throw(_("An item can only be selected once in {0}.").format(self.meta.get_label(table_field)))
		if not selected:
			return
		if source_doctype == "Preparation Area":
			available = set(frappe.get_all(source_doctype, filters={
				"store": ["in", list(stores)], "enabled": 1, "has_kds": 1,
			}, pluck=source_field))
		else:
			available = set(frappe.get_all(source_doctype, filters={
				"parent": ["in", list(stores)], "parenttype": "Store",
			}, pluck=source_field))
		for value in selected:
			if not frappe.db.get_value(doctype, {"name": value, "enabled": 1}, "name"):
				frappe.throw(_("Select enabled {0} records only.").format(doctype))
			if value not in available:
				frappe.throw(_("{0} must be available in at least one assigned Store.").format(doctype))

	def validate_user(self):
		if not frappe.db.get_value("User", {"name": self.user, "enabled": 1}, "name"):
			frappe.throw(_("Select an enabled Frappe User."))
			
		duplicate = frappe.db.exists("POS User", {"user": self.user, "name": ["!=", self.name]})
		if duplicate:
			frappe.throw(_("A POS User record already exists for this Frappe User."))

	def validate_employee(self):
		if not self.employee:
			return
		employee = frappe.db.get_value("Employee", self.employee, ["status", "user_id"], as_dict=True)
		if not employee or employee.status != "Active":
			frappe.throw(_("Select an active ERPNext Employee."))
		if employee.user_id and employee.user_id != self.user:
			frappe.throw(_("The selected Employee is linked to a different Frappe User."))

	def validate_stores(self):
		if not self.stores:
			frappe.throw(_("Assign this POS User to at least one Store."))
		default_stores = [row.store for row in self.stores if row.default_store]
		if len(default_stores) > 1:
			frappe.throw(_("Only one Store can be the default for a POS User."))
		seen = set()
		for row in self.stores:
			if row.store in seen:
				frappe.throw(_("A Store can only be assigned once."))
			seen.add(row.store)
			if not frappe.db.get_value("Store", {"name": row.store, "enabled": 1}, "name"):
				frappe.throw(_("Select enabled Stores only."))
