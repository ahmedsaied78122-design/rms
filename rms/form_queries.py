"""Permission-aware dependent link choices for RMS setup forms.

These queries only improve selection UX; document controllers remain authoritative.
"""
import frappe
from frappe import _


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def scoped_link(doctype, txt, searchfield, start, page_len, filters):
	allowed = {"Restaurant Brand", "Order Type", "Preparation Area", "POS Profile"}
	if doctype not in allowed:
		frappe.throw(_("Unsupported RMS link target."), frappe.PermissionError)
	args = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	requested = args.get("stores") or []
	if not isinstance(requested, list) or len(requested) > 200 or any(not isinstance(x, str) for x in requested):
		frappe.throw(_("Choose valid stores before selecting this field."))
	stores = frappe.get_list("Store", filters={"name": ["in", requested], "enabled": 1},
		fields=["name", "company"], limit_page_length=200) if requested else []
	if not stores:
		return []
	store_names = [row.name for row in stores]
	query_filters = {"enabled": 1}
	if doctype in ("Restaurant Brand", "Order Type"):
		source, value = ("Store Brand Assignment", "restaurant_brand") if doctype == "Restaurant Brand" else ("Store Order Type Tax", "order_type")
		# Only children of stores already returned by the permission-aware parent query.
		values = frappe.get_all(source, filters={"parenttype": "Store", "parent": ["in", store_names]}, pluck=value)
		if not values:
			return []
		query_filters["name"] = ["in", sorted(set(values))]
	elif doctype == "Preparation Area":
		query_filters["store"] = ["in", store_names]
		if args.get("kds_only"):
			query_filters["has_kds"] = 1
	elif doctype == "POS Profile":
		query_filters = {"disabled": 0, "company": ["in", sorted({row.company for row in stores if row.company})]}
	if txt:
		# These RMS master records use their title as name; no dynamic SQL/search columns.
		query_filters["name"] = ["like", "%" + txt + "%"] if "name" not in query_filters else query_filters["name"]
		or_filters = {"name": ["like", "%" + txt + "%"]}
	else:
		or_filters = None
	rows = frappe.get_list(doctype, filters=query_filters, or_filters=or_filters, fields=["name"],
		order_by="name asc", start=max(0, int(start or 0)), limit_page_length=min(50, max(1, int(page_len or 20))))
	return [[row.name] for row in rows]
