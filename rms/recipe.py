import base64
import binascii

import frappe
from frappe import _
from frappe.utils import flt


def get_additional_recipe_order_types(value):
	"""Decode stable, comma-safe tokens stored by the child-table MultiSelect field."""
	if not value:
		return []

	names = []
	for token in str(value).split(","):
		token = token.strip()
		if not token:
			continue
		try:
			padded = token.replace("-", "+").replace("_", "/")
			padded += "=" * (-len(padded) % 4)
			name = base64.b64decode(padded.encode("ascii"), validate=True).decode("utf-8")
		except (binascii.Error, ValueError, UnicodeDecodeError, UnicodeEncodeError):
			frappe.throw(_("Additional Recipe Order Types contain an invalid selection."))
		if not name or name in names:
			frappe.throw(_("Additional Recipe Order Types must be valid and unique."))
		names.append(name)
	return names


def get_recipe_components(product, product_qty, warehouse, order_type=None):
	"""Expand a Selling Product recipe into stock Item snapshots."""
	if not product.with_recipe:
		return []
	if not warehouse:
		frappe.throw(_("A source Warehouse is required for Recipe consumption."))

	components = []
	for recipe in product.recipe:
		qty = flt(recipe.qty) * flt(product_qty)
		if recipe.sub_recipe:
			components.extend(_explode_bom(recipe.item, qty, warehouse, bool(recipe.multi_level), set()))
		else:
			components.append(_component(recipe.item, qty, warehouse))

	if order_type:
		for recipe in product.additional_recipe:
			if order_type in get_additional_recipe_order_types(recipe.order_types):
				components.append(_component(recipe.item, flt(recipe.qty) * flt(product_qty), warehouse))
	return components


def _explode_bom(item_code, qty, warehouse, multi_level, path):
	if item_code in path:
		frappe.throw(_("Circular Sub Recipe detected for Item {0}.").format(item_code))
	bom = frappe.get_all(
		"BOM",
		filters={"item": item_code, "is_active": 1, "docstatus": 1},
		fields=["name", "quantity"],
		order_by="is_default desc, creation desc",
		limit_page_length=1,
	)
	if not bom:
		frappe.throw(_("No active submitted BOM exists for Sub Recipe Item {0}.").format(item_code))
	bom_doc = frappe.get_doc("BOM", bom[0].name)
	path = path | {item_code}
	result = []
	for row in bom_doc.items:
		component_qty = flt(row.stock_qty or row.qty) * flt(qty) / flt(bom_doc.quantity or 1)
		child_bom = frappe.db.exists("BOM", {"item": row.item_code, "is_active": 1, "docstatus": 1})
		if multi_level and child_bom:
			result.extend(_explode_bom(row.item_code, component_qty, warehouse, True, path))
		else:
			result.append(_component(row.item_code, component_qty, warehouse))
	return result


def _component(item_code, qty, warehouse):
	item = frappe.db.get_value(
		"Item", item_code, ["is_stock_item", "disabled", "stock_uom", "valuation_rate"], as_dict=True
	)
	if not item or not item.is_stock_item or item.disabled:
		frappe.throw(_("Recipe Item {0} must be enabled and Maintain Stock must be on.").format(item_code))
	return {
		"item": item_code,
		"qty": flt(qty),
		"uom": item.stock_uom,
		"warehouse": warehouse,
		"cost": flt(item.valuation_rate),
	}
