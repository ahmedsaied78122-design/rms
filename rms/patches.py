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
