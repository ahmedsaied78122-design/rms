import frappe
from frappe import _
from frappe.model.document import Document


class StoreMenu(Document):
	def validate(self):
		if not frappe.db.get_value("Restaurant Brand", self.restaurant_brand, "enabled"):
			frappe.throw(_("Menu must belong to an enabled Brand."))
		categories = [row.product_category for row in self.categories if row.product_category]
		if len(categories) != len(set(categories)):
			frappe.throw(_("A Product Category can only appear once in a Menu."))
		for category in categories:
			if not frappe.db.get_value("Product Category", category, "enabled"):
				frappe.throw(_("Menu categories must be enabled Product Categories."))
