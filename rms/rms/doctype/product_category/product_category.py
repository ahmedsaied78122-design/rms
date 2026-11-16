import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet


class ProductCategory(NestedSet):
	def validate(self):
		if self.parent_product_category == self.name:
			frappe.throw(_("A Product Category cannot be its own parent."))
		if self.parent_product_category:
			parent = frappe.db.get_value(
				"Product Category", self.parent_product_category, ["enabled", "is_group", "lft", "rgt"], as_dict=True
			)
			if not parent or not parent.enabled or not parent.is_group:
				frappe.throw(_("Parent Product Category must be enabled and marked Is Group."))
			current = frappe.db.get_value("Product Category", self.name, ["lft", "rgt"], as_dict=True) if self.name else None
			if current and current.lft <= parent.lft <= current.rgt:
				frappe.throw(_("A Product Category cannot be moved under one of its own descendants."))

		if not self.is_group and not self.item_group:
			frappe.throw(_("Select an Item Group for each leaf Product Category."))
		if self.item_group and frappe.db.get_value("Item Group", self.item_group, "is_group"):
			frappe.throw(_("Choose a leaf Item Group for this Product Category."))
		if self.default_warehouse and not frappe.db.exists(
			"Warehouse", {"name": self.default_warehouse, "is_group": 0, "disabled": 0}
		):
			frappe.throw(_("Default Warehouse must be an enabled leaf Warehouse."))

		if self.default_preparation_area and not frappe.db.get_value(
			"Preparation Area", self.default_preparation_area, "enabled"
		):
			frappe.throw(_("Default Preparation Area must be enabled."))
