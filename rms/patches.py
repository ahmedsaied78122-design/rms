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
