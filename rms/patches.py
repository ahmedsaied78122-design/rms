import frappe


def backfill_pos_order_item_confirmation_from_kitchen_tickets():
	"""Backfill line confirmation once, using the kitchen ticket as evidence."""
	if not frappe.db.has_column("POS Order Item", "sent_to_kitchen"):
		return
	if not frappe.db.table_exists("Kitchen Ticket Item"):
		return

	frappe.db.sql("""
		UPDATE `tabPOS Order Item` poi
		SET sent_to_kitchen = EXISTS (
			SELECT 1
			FROM `tabKitchen Ticket Item` kti
			WHERE kti.pos_order_item = poi.name
		)
		WHERE poi.parenttype = 'POS Order'
	""")


def enable_negative_stock_by_default():
	"""Enable per-item negative stock and make it the default for new items."""
	if frappe.db.has_column("Item", "allow_negative_stock"):
		frappe.db.sql("UPDATE `tabItem` SET allow_negative_stock = 1")
	if frappe.db.has_column("Selling Product", "allow_negative_stock"):
		frappe.db.sql("UPDATE `tabSelling Product` SET allow_negative_stock = 1")

	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	filters = {
		"doc_type": "Item",
		"doctype_or_field": "DocField",
		"field_name": "allow_negative_stock",
		"property": "default",
	}
	setter_name = frappe.db.get_value("Property Setter", filters, "name")
	if setter_name:
		frappe.db.set_value("Property Setter", setter_name, {"value": "1", "property_type": "Text"}, update_modified=False)
	else:
		make_property_setter("Item", "allow_negative_stock", "default", "1", "Text")

	frappe.clear_cache(doctype="Item")
	frappe.clear_cache(doctype="Selling Product")


def initialize_pos_operation_permissions():
	"""Preserve direct manager actions once; later checkbox changes stay authoritative."""
	for row in frappe.get_all('POS User',fields=['name','user']):
		manager=bool(set(frappe.get_roles(row.user)) & {'POS Manager','System Manager'})
		frappe.db.set_value('POS User',row.name,dict(can_void_items=int(manager),can_void_waste=int(manager),can_return_waste=int(manager)),update_modified=False)


def migrate_product_modifier_limits():
	"""Freeze legacy effective limits on product rows before retiring shared editing."""
	from rms.rms.doctype.selling_product_modifier_group.selling_product_modifier_group import (
		get_maximum_selections,
		get_minimum_selections,
	)

	rows = frappe.get_all(
		"Selling Product Modifier Group", fields=["name", "modifier_group", "selection_requirement"]
	)
	groups = {
		group.name: group
		for group in frappe.get_all(
			"Modifier Group", fields=["name", "min_selections", "max_selections", "allow_multiple_selections"]
		)
	}
	# Child-table schema only: no parent role permission declarations are reimported.
	frappe.reload_doc("rms", "doctype", "selling_product_modifier_group", force=True)
	for row in rows:
		group = groups.get(row.modifier_group, frappe._dict())
		frappe.db.set_value(
			"Selling Product Modifier Group", row.name,
			{
				"min_selections": get_minimum_selections(row, group.get("min_selections") or 0),
				"max_selections": get_maximum_selections(group),
			},
			update_modified=False,
		)
	for doctype in ("Selling Product Modifier Group", "Selling Product"):
		frappe.db.set_value("DocType", doctype, "modified", frappe.utils.now_datetime(), update_modified=False)
		frappe.clear_cache(doctype=doctype)
