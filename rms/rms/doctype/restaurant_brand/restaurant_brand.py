import frappe
from frappe import _
from frappe.model.document import Document


class RestaurantBrand(Document):
	def validate(self):
		if self.brand_code:
			duplicate = frappe.db.exists(
				"Restaurant Brand", {"brand_code": self.brand_code, "name": ["!=", self.name or ""]}
			)
			if duplicate:
				frappe.throw(_("Brand Code must be unique."))

		menus = [row.store_menu for row in self.menus if row.store_menu]
		if len(menus) != len(set(menus)):
			frappe.throw(_("A Menu can only be assigned once to a Brand."))
		for menu in menus:
			menu_brand, menu_enabled = frappe.db.get_value(
				"Store Menu", menu, ["restaurant_brand", "enabled"]
			)
			if menu_brand != self.name or not menu_enabled:
				frappe.throw(_("Each assigned Menu must be enabled and belong to this Brand."))
