import frappe
from frappe import _
from frappe.utils import flt, nowdate, nowtime

from erpnext.stock.get_item_details import get_conversion_factor


def create_material_issue(company, items, expense_account=None, remarks=None):
	"""Create one standard ERPNext Material Issue for stock component rows."""
	quantities = {}
	for row in items:
		key = (row.get("item"), row.get("warehouse"), row.get("uom"))
		quantities[key] = quantities.get(key, 0) + flt(row.get("qty"))
	quantities = {key: qty for key, qty in quantities.items() if qty > 0}
	if not quantities:
		return None

	stock_entry_type = frappe.db.get_value("Stock Entry Type", {"purpose": "Material Issue"}, "name")
	if not stock_entry_type:
		frappe.throw(_("Create a standard Stock Entry Type for Material Issue first."))
	company_doc = frappe.get_doc("Company", company)
	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = stock_entry_type
	entry.purpose = "Material Issue"
	entry.company = company
	entry.posting_date = nowdate()
	entry.posting_time = nowtime()
	entry.set_posting_time = 1
	entry.remarks = remarks
	for (item_code, warehouse, uom), qty in quantities.items():
		if not item_code or not warehouse:
			frappe.throw(_("Every stock component needs an Item and Source Warehouse."))
		item = frappe.db.get_value("Item", item_code, ["disabled", "stock_uom"], as_dict=True)
		if not item or item.disabled:
			frappe.throw(_("Item {0} is unavailable for stock consumption.").format(item_code))
		conversion_factor = get_conversion_factor(item_code, uom).get("conversion_factor", 1)
		entry.append("items", {
			"item_code": item_code,
			"qty": qty,
			"uom": uom or item.stock_uom,
			"stock_uom": item.stock_uom,
			"conversion_factor": conversion_factor,
			"s_warehouse": warehouse,
			"expense_account": expense_account,
			"cost_center": company_doc.cost_center,
		})
	entry.set_missing_values()
	entry.flags.ignore_permissions = True
	entry.insert(ignore_permissions=True)
	entry.submit()
	return entry.name


def create_material_receipt(company, items, remarks=None):
	"""Receive eligible returned Items through a standard ERPNext Stock Entry."""
	quantities = {}
	for row in items:
		key = (row.get("item"), row.get("warehouse"), row.get("uom"),
			row.get("expense_account"), flt(row.get("basic_rate")))
		quantities[key] = quantities.get(key, 0) + flt(row.get("qty"))
	quantities = {key: qty for key, qty in quantities.items() if qty > 0}
	if not quantities:
		return None
	stock_entry_type = frappe.db.get_value("Stock Entry Type", {"purpose": "Material Receipt"}, "name")
	if not stock_entry_type:
		frappe.throw(_("Create a standard Stock Entry Type for Material Receipt first."))
	company_doc = frappe.get_doc("Company", company)
	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = stock_entry_type
	entry.purpose = "Material Receipt"
	entry.company = company
	entry.posting_date = nowdate()
	entry.posting_time = nowtime()
	entry.set_posting_time = 1
	entry.remarks = remarks
	for (item_code, warehouse, uom, expense_account, basic_rate), qty in quantities.items():
		if not item_code or not warehouse:
			frappe.throw(_("Every returned stock Item needs an Item and Target Warehouse."))
		item = frappe.db.get_value("Item", item_code, ["disabled", "stock_uom", "valuation_rate"], as_dict=True)
		if not item or item.disabled:
			frappe.throw(_("Item {0} is unavailable for stock receipt.").format(item_code))
		conversion_factor = get_conversion_factor(item_code, uom).get("conversion_factor", 1)
		entry.append("items", {
			"item_code": item_code,
			"qty": qty,
			"uom": uom or item.stock_uom,
			"stock_uom": item.stock_uom,
			"conversion_factor": conversion_factor,
			"t_warehouse": warehouse,
			"basic_rate": basic_rate or flt(item.valuation_rate),
			"expense_account": expense_account,
			"cost_center": company_doc.cost_center,
		})
	entry.set_missing_values()
	entry.flags.ignore_permissions = True
	entry.insert(ignore_permissions=True)
	entry.submit()
	return entry.name
