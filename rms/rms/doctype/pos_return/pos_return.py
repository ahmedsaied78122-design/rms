import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from rms.snapshots import parse_json_rows


def get_return_refund_total(invoice):
	return abs(flt(invoice.grand_total))


def normalize_return_rounding(invoice):
	invoice.rounded_total = invoice.grand_total
	invoice.rounding_adjustment = 0
	if hasattr(invoice, "base_grand_total"):
		invoice.base_rounded_total = invoice.base_grand_total
		invoice.base_rounding_adjustment = 0
	return invoice


class POSReturn(Document):
	def before_insert(self):
		if self.status not in (None, "", "Pending Approval"):
			frappe.throw(_("A new POS Return must start Pending Approval."))
		self.status = "Pending Approval"

	def validate(self):
		if self.is_new() or self.get_doc_before_save() is None:
			self.validate_request()
			return
		if self.flags.get("allow_workflow_update"):
			return
		previous = self.get_doc_before_save()
		if previous.status != self.status or previous.items != self.items or previous.payments != self.payments:
			frappe.throw(_("A submitted POS Return request cannot be edited."))

	def validate_request(self):
		if not self.source_pos_invoice or not self.cashier_session:
			frappe.throw(_("Source POS Invoice and Cashier Session are required."))
		session = frappe.db.get_value("Cashier Session", self.cashier_session,
			["store", "user", "pos_profile", "status"], as_dict=True)
		source = frappe.db.get_value("POS Invoice", self.source_pos_invoice,
			["docstatus", "is_return", "pos_profile", "customer", "owner", "return_against"], as_dict=True)
		if not session or session.status != "Open" or session.store != self.store:
			frappe.throw(_("Return requires an Open Cashier Session for the selected Store."))
		if not source or source.docstatus != 1 or source.is_return or source.pos_profile != session.pos_profile:
			frappe.throw(_("Choose a submitted, non-return POS Invoice from this Store's POS Profile."))
		if source.owner != session.user:
			frappe.throw(_("Only sales created by the active cashier can be returned in this session."))
		self.customer = source.customer
		if not self.items or not self.payments:
			frappe.throw(_("Add returned items and refund payments."))
		seen_items = set()
		self.refund_total = 0
		for row in self.items:
			if row.source_pos_invoice_item in seen_items:
				frappe.throw(_("Each source invoice line can appear only once."))
			seen_items.add(row.source_pos_invoice_item)
			self.validate_return_line(row)
		seen_methods = set()
		payment_total = 0
		allowed_methods = {row.mode_of_payment for row in frappe.get_all("POS Payment Method",
			filters={"parent": session.pos_profile, "parenttype": "POS Profile", "allow_in_returns": 1},
			fields=["mode_of_payment"])}
		for payment in self.payments:
			if payment.mode_of_payment not in allowed_methods or payment.mode_of_payment in seen_methods:
				frappe.throw(_("Refund methods must be unique methods configured on the active POS Profile."))
			seen_methods.add(payment.mode_of_payment)
			if flt(payment.amount) <= 0:
				frappe.throw(_("Refund payment amounts must be positive."))
			payment_total += flt(payment.amount)
		invoice = self.build_return_invoice()
		self.refund_total = get_return_refund_total(invoice)
		if abs(payment_total - self.refund_total) > 0.01:
			frappe.throw(_("Refund payments must equal the ERPNext credit note total of {0}.").format(self.refund_total))

	def validate_return_line(self, row):
		source_line = frappe.db.get_value("POS Invoice Item", row.source_pos_invoice_item,
			["parent", "item_code", "qty", "rate", "warehouse", "uom", "rms_pos_order_item"], as_dict=True)
		if not source_line or source_line.parent != self.source_pos_invoice:
			frappe.throw(_("Each return line must belong to the source POS Invoice."))
		if not source_line.rms_pos_order_item:
			frappe.throw(_("This POS Invoice line has no RMS POS Order Item reference and cannot be returned through this workflow."))
		order_item = frappe.db.get_value("POS Order Item", source_line.rms_pos_order_item,
			["parent", "item", "warehouse", "modifiers"], as_dict=True)
		order = frappe.db.get_value("POS Order", order_item.parent if order_item else None,
			["status", "cashier_session", "store"], as_dict=True) if order_item else None
		if not order or order.status != "Paid" or order.cashier_session != self.cashier_session or order.store != self.store:
			frappe.throw(_("Return line must belong to a paid RMS order in the active session."))
		modifier_items = {row.get("item") for row in parse_json_rows(order_item.modifiers)}
		if order_item.item != source_line.item_code and source_line.item_code not in modifier_items:
			frappe.throw(_("Source Item must match the product or one of its saved modifiers."))
		if flt(row.qty) <= 0:
			frappe.throw(_("Return quantities must be greater than zero."))
		if frappe.db.get_value("UOM", source_line.uom, "must_be_whole_number") and flt(row.qty) % 1:
			frappe.throw(_("Return quantity must be a whole number for Unit {0}.").format(source_line.uom))
		row.item_code = source_line.item_code
		row.uom = source_line.uom
		row.pos_order_item = source_line.rms_pos_order_item
		row.rate = flt(source_line.rate)
		row.amount = flt(row.qty) * flt(row.rate)
		row.warehouse = order_item.warehouse
		reserved = self.get_reserved_qty(row.source_pos_invoice_item, exclude_return=self.name)
		if flt(row.qty) > flt(source_line.qty) - reserved:
			frappe.throw(_("Return quantity exceeds the sold quantity remaining after pending and approved returns."))

	def build_return_invoice(self):
		from erpnext.accounts.doctype.pos_invoice.pos_invoice import make_sales_return
		from rms.taxes import prevent_pos_item_price_autoinsert

		actor = frappe.session.user
		try:
			frappe.set_user("Administrator")
			invoice = frappe.new_doc("POS Invoice")
			with prevent_pos_item_price_autoinsert(invoice):
				invoice = make_sales_return(self.source_pos_invoice, invoice)
		finally:
			frappe.set_user(actor)
		requested = {row.source_pos_invoice_item: flt(row.qty) for row in self.items}
		invoice.items = [row for row in invoice.items if row.pos_invoice_item in requested]
		if len(invoice.items) != len(requested):
			frappe.throw(_("ERPNext could not map each selected line to the source POS Invoice."))
		for row in invoice.items:
			qty = requested[row.pos_invoice_item]
			row.qty = -qty
			row.stock_qty = -qty * flt(row.conversion_factor or 1)
			row.amount = -qty * flt(row.rate)
			row.base_amount = row.amount * flt(invoice.conversion_rate or 1)
			row.net_amount = row.amount
			row.base_net_amount = row.base_amount
		# Actual charges do not vary with quantity, so prorate them to selected source-line value.
		source = frappe.get_doc("POS Invoice", self.source_pos_invoice)
		source_amount = sum(abs(flt(row.amount)) for row in source.items)
		selected_amount = sum(abs(flt(row.amount)) for row in invoice.items)
		actual_ratio = selected_amount / source_amount if source_amount else 0
		for tax in invoice.taxes:
			if tax.charge_type == "Actual":
				source_tax = next((row for row in source.taxes if row.idx == tax.idx), None)
				tax.tax_amount = -abs(flt(source_tax.tax_amount) if source_tax else flt(tax.tax_amount)) * actual_ratio
		invoice.update_stock = 0
		invoice.set("payments", [])
		invoice.calculate_taxes_and_totals()
		return normalize_return_rounding(invoice)

	@staticmethod
	def get_reserved_qty(source_item, exclude_return=None):
		exclude_clause = "and ret.name != %(exclude_return)s" if exclude_return else ""
		query = """
			select item.qty
			from `tabPOS Return Item` item
			inner join `tabPOS Return` ret on ret.name = item.parent
			where item.source_pos_invoice_item = %(source_item)s
			and ret.status in ('Pending Approval', 'Approved')
			and ret.docstatus < 2
		""".replace("and ret.docstatus < 2", "and ret.docstatus < 2 " + exclude_clause) + " for update"
		rows = frappe.db.sql(query, {"source_item": source_item, "exclude_return": exclude_return}, as_dict=True)
		return sum(flt(row.qty) for row in rows) + POSReturn.get_external_returned_qty(source_item)

	@staticmethod
	def get_external_returned_qty(source_item):
		source_invoice = frappe.db.get_value("POS Invoice Item", source_item, "parent")
		if not source_invoice:
			return 0
		return_invoices = frappe.get_all("POS Invoice", filters={
			"return_against": source_invoice, "is_return": 1, "docstatus": 1,
		}, pluck="name")
		if not return_invoices:
			return 0
		linked_returns = set(frappe.get_all("POS Return", filters={
			"return_pos_invoice": ["in", return_invoices], "status": "Approved",
		}, pluck="return_pos_invoice"))
		quantity = 0
		for invoice_name in set(return_invoices) - linked_returns:
			quantity += abs(flt(frappe.db.get_value("POS Invoice Item", {
				"parent": invoice_name, "parenttype": "POS Invoice", "pos_invoice_item": source_item,
			}, "qty") or 0))
		return quantity

	def build_stock_receipt_items(self):
		items = []
		for returned in self.items:
			if returned.is_waste:
				continue
			source_line = frappe.get_doc("POS Invoice Item", returned.source_pos_invoice_item)
			order_item = frappe.get_doc("POS Order Item", returned.pos_order_item)
			product_name = frappe.db.get_value("Selling Product", {"item": source_line.item_code}, "name")
			if not product_name:
				frappe.throw(_("The returned Item is no longer linked to a Selling Product."))
			product = frappe.get_doc("Selling Product", product_name)
			order = frappe.get_doc("POS Order", order_item.parent)
			cogs_account = frappe.db.get_value("Order Type Account Mapping", {
				"parent": order.order_type, "parenttype": "Order Type", "company": frappe.db.get_value("Store", self.store, "company"),
			}, "cost_of_goods_sold_account")
			stockable_item = product.with_recipe or (
				product.maintain_stock and frappe.db.get_value("Item", source_line.item_code, "is_stock_item")
			)
			if stockable_item and not cogs_account:
				frappe.throw(_("Configure the Order Type Cost of Goods Sold Account before receiving returned stock."))
			if product.with_recipe:
				components = parse_json_rows(order_item.recipe_snapshot)
				product_components = [row for row in components if row.get("source_selling_product") == product.name]
				if components and not any(row.get("source_selling_product") for row in components):
					if flt(returned.qty) != flt(abs(source_line.qty)):
						frappe.throw(_("This saved recipe snapshot cannot safely allocate a partial stock return."))
					product_components = components
				ratio = flt(returned.qty) / flt(abs(source_line.qty) or 1)
				for component in product_components:
					items.append({"item": component.item, "qty": flt(component.qty) * ratio,
						"uom": component.uom, "warehouse": component.warehouse,
						"expense_account": cogs_account, "basic_rate": flt(component.cost)})
			elif product.maintain_stock and frappe.db.get_value("Item", source_line.item_code, "is_stock_item"):
				items.append({"item": source_line.item_code, "qty": flt(returned.qty),
					"uom": source_line.stock_uom, "warehouse": source_line.warehouse, "expense_account": cogs_account})
		return items
