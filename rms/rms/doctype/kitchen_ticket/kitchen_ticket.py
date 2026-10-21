import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime


class KitchenTicket(Document):
	def before_insert(self):
		self.status = "Pending"
		self.sent_at = self.sent_at or now_datetime()

	def validate(self):
		self.validate_context()
		self.validate_items()
		self.stamp_status_times()

	def validate_context(self):
		order = frappe.db.get_value("POS Order", self.pos_order, ["store", "status"], as_dict=True)
		if not order or order.store != self.store or order.status not in (
			"Confirmed",
			"In Preparation",
			"Ready",
		):
			frappe.throw(_("Kitchen Ticket must belong to a confirmed POS Order for the same Store."))
		area = frappe.db.get_value(
			"Preparation Area", self.preparation_area, ["store", "enabled", "has_kds", "has_printer"], as_dict=True
		)
		if not area or area.store != self.store or not area.enabled:
			frappe.throw(_("Preparation Area must be enabled and belong to the Ticket Store."))
		if not area.has_kds and not area.has_printer:
			frappe.throw(_("Preparation Area needs KDS or Printer output."))

	def validate_items(self):
		order_item_names = set(
			frappe.get_all(
				"POS Order Item", filters={"parent": self.pos_order, "parenttype": "POS Order"}, pluck="name"
			)
		)
		seen = set()
		for row in self.items:
			if row.pos_order_item not in order_item_names:
				frappe.throw(_("Every Kitchen Ticket line must belong to the Ticket POS Order."))
			if row.pos_order_item in seen:
				frappe.throw(_("A POS Order line can only be added once to a Preparation Area Ticket."))
			seen.add(row.pos_order_item)
			product, order_qty = frappe.db.get_value(
				"POS Order Item", row.pos_order_item, ["selling_product", "qty"]
			)
			if product != row.selling_product or flt(row.qty) > flt(order_qty):
				frappe.throw(_("Kitchen Ticket quantity and product must match its POS Order line."))
		if not self.items:
			frappe.throw(_("A Kitchen Ticket needs at least one product line."))

	def stamp_status_times(self):
		previous = self.get_doc_before_save()
		if not previous or previous.status != self.status:
			if self.status == "Started":
				self.started_at = now_datetime()
			elif self.status == "Ready":
				self.ready_at = now_datetime()
			elif self.status == "Picked":
				self.picked_at = now_datetime()

	def set_status(self, status):
		allowed = {
			"Pending": {"Started", "Cancelled"},
			"Started": {"Ready", "Cancelled"},
			"Ready": {"Picked", "Cancelled"},
			"Picked": set(),
			"Cancelled": set(),
		}
		if status not in allowed.get(self.status, set()):
			frappe.throw(_("Invalid Kitchen Ticket status change from {0} to {1}.").format(self.status, status))
		self.status = status
		for row in self.items:
			row.status = status
		self.save(ignore_permissions=True)
		if not self.flags.get("skip_order_status_sync"):
			self.update_order_status()
		return self

	def update_order_status(self):
		order = frappe.get_doc("POS Order", self.pos_order)
		tickets = frappe.get_all(
			"Kitchen Ticket",
			filters={"pos_order": self.pos_order},
			fields=["status"],
			ignore_permissions=True,
		)
		active = [ticket.status for ticket in tickets if ticket.status != "Cancelled"]
		if active and all(status in ("Ready", "Picked") for status in active):
			order.set_kitchen_status("Ready")
		elif any(status in ("Started", "Ready", "Picked") for status in active):
			order.set_kitchen_status("In Preparation")
