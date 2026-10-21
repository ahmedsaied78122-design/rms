import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from rms.recipe import get_recipe_components
from rms.stock import create_material_issue


class WasteEntry(Document):
	def validate(self):
		previous = self.get_doc_before_save()
		if previous and previous.docstatus == 1:
			return
		self.validate_context()
		self.build_waste_items()
		self.status = "Draft"

	def validate_context(self):
		store = frappe.db.get_value("Store", self.store, ["company", "enabled"], as_dict=True)
		if not store or not store.enabled:
			frappe.throw(_("Choose an enabled Store."))
		self.store_company = store.company
		product = frappe.get_doc("Selling Product", self.selling_product)
		if not product.enabled:
			frappe.throw(_("Choose an enabled Selling Product."))
		if flt(self.quantity) <= 0:
			frappe.throw(_("Waste Quantity must be greater than zero."))
		defaults = product.get_effective_defaults(self.store)
		self.warehouse = self.warehouse or defaults["warehouse"]
		warehouse = frappe.db.get_value("Warehouse", self.warehouse, ["company", "is_group", "disabled"], as_dict=True)
		if not warehouse or warehouse.company != store.company or warehouse.is_group or warehouse.disabled:
			frappe.throw(_("Choose an enabled leaf Warehouse that belongs to the Store Company."))
		if self.order_type:
			if not frappe.db.get_value("Order Type", self.order_type, "enabled"):
				frappe.throw(_("Choose an enabled Order Type."))
			if not frappe.db.exists("Store Order Type Tax", {
				"parent": self.store, "parenttype": "Store", "order_type": self.order_type,
			}):
				frappe.throw(_("Order Type must be assigned to the Store."))

	def build_waste_items(self):
		product = frappe.get_doc("Selling Product", self.selling_product)
		if product.with_recipe:
			components = get_recipe_components(product, self.quantity, self.warehouse, self.order_type)
		else:
			item = frappe.db.get_value("Item", product.item, ["is_stock_item", "disabled", "stock_uom", "valuation_rate"], as_dict=True)
			if not product.maintain_stock or not item or not item.is_stock_item or item.disabled:
				frappe.throw(_("Waste can only be recorded for a recipe product or a stock-maintained product."))
			components = [{"item": product.item, "qty": flt(self.quantity), "uom": item.stock_uom,
				"warehouse": self.warehouse, "cost": flt(item.valuation_rate)}]
		if not components:
			frappe.throw(_("The Selling Product has no stock components to waste."))
		self.set("items", [])
		for component in components:
			self.append("items", {
				"item": component["item"],
				"qty": component["qty"],
				"uom": component["uom"],
				"basic_rate": component["cost"],
				"amount": flt(component["qty"]) * flt(component["cost"]),
				"warehouse": component["warehouse"],
			})

	def on_submit(self):
		store_company = frappe.db.get_value("Store", self.store, "company")
		expense_account = None
		if self.order_type:
			expense_account = frappe.db.get_value("Order Type Account Mapping", {
				"parent": self.order_type, "parenttype": "Order Type", "company": store_company,
			}, "cost_of_goods_sold_account")
		stock_entry = create_material_issue(
			store_company,
			[self.row_as_stock_item(row) for row in self.items],
			expense_account,
			_("Waste {0}: {1}").format(self.name, self.reason),
		)
		if not stock_entry:
			frappe.throw(_("The waste record did not produce any stock movement."))
		frappe.db.set_value("Waste Entry", self.name, {"stock_entry": stock_entry, "status": "Submitted"}, update_modified=False)
		self.stock_entry = stock_entry
		self.status = "Submitted"

	def on_cancel(self):
		if self.stock_entry and frappe.db.get_value("Stock Entry", self.stock_entry, "docstatus") == 1:
			stock_entry = frappe.get_doc("Stock Entry", self.stock_entry)
			stock_entry.flags.ignore_permissions = True
			stock_entry.cancel()
		frappe.db.set_value("Waste Entry", self.name, "status", "Cancelled", update_modified=False)
		self.status = "Cancelled"

	@staticmethod
	def row_as_stock_item(row):
		return {"item": row.item, "qty": row.qty, "uom": row.uom, "warehouse": row.warehouse}
