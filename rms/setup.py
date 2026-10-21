import frappe


def ensure_pos_roles():
	"""Install the operational roles referenced by POS API permission checks."""
	for role_name in ("POS Cashier", "POS Manager", "Kitchen Operator"):
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 1}).insert(ignore_permissions=True)
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
	create_custom_fields({
		"POS Invoice Item": [{
			"fieldname": "rms_pos_order_item",
			"label": "RMS POS Order Item",
			"fieldtype": "Link",
			"options": "POS Order Item",
			"read_only": 1,
			"no_copy": 1,
			"hidden": 1,
			"insert_after": "pos_invoice_item",
		}],
		"POS Invoice": [{
			"fieldname": "rms_guest_payment_breakdown",
			"label": "RMS Guest Payment Breakdown",
			"fieldtype": "Code",
			"options": "JSON",
			"read_only": 1,
			"no_copy": 1,
			"hidden": 1,
			"insert_after": "payments",
		}]
	}, update=True)
	# Product Category is a nested set; populate tree bounds for rows created before this schema.
	from frappe.utils.nestedset import rebuild_tree
	rebuild_tree("Product Category")
	# Table context is valid only for order types that require a dining table.
	# Normalize legacy Takeaway/Delivery orders so they cannot reserve a dining table.
	tableless_order_types = frappe.get_all("Order Type", filters={"require_table": 0}, pluck="name")
	if tableless_order_types:
		legacy_orders = frappe.get_all("POS Order", filters={"order_type": ["in", tableless_order_types]},
			fields=["name", "dining_area", "dining_table"])
		for order in legacy_orders:
			if order.dining_area or order.dining_table:
				frappe.db.set_value("POS Order", order.name, {"dining_area": None, "dining_table": None}, update_modified=False)
