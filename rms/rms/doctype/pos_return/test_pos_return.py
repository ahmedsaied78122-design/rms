import unittest
from unittest.mock import Mock, patch

import frappe

from rms.rms.doctype.pos_return.pos_return import POSReturn, get_return_refund_total, normalize_return_rounding
from rms.api.pos import approve_pos_return, get_pos_return_permission_query


class TestPOSReturnLineValidation(unittest.TestCase):
	def test_brand_rounding_uses_the_same_rule_for_negative_credit_totals(self):
		for method, expected in (("Round Up", 81), ("Nearest", 80), ("Round Down", 80), ("No Rounding", 80.49)):
			with self.subTest(method=method):
				invoice = frappe._dict(grand_total=-80.49, base_grand_total=-80.49, conversion_rate=1)
				normalize_return_rounding(invoice, method)
				self.assertEqual(get_return_refund_total(invoice), expected)
				self.assertEqual(invoice.rounded_total, -expected)
				self.assertEqual(invoice.base_rounded_total, -expected)

	def test_refund_uses_exact_credit_total_instead_of_rounded_display_total(self):
		invoice = frappe._dict(grand_total=-28.5, rounded_total=-28, rounding_adjustment=0.5,
			base_grand_total=-28.5, base_rounded_total=-28, base_rounding_adjustment=0.5)
		normalize_return_rounding(invoice)
		self.assertEqual(invoice.rounded_total, -28.5)
		self.assertEqual(invoice.rounding_adjustment, 0)
		self.assertEqual(get_return_refund_total(invoice), 28.5)

	def setUp(self):
		self.ret = frappe.get_doc({"doctype": "POS Return"})
		self.ret.store = "STORE-1"
		self.ret.cashier_session = "SESSION-1"
		self.ret.source_pos_invoice = "POS-INV-1"

	def test_line_must_belong_to_selected_invoice(self):
		with patch("frappe.db.get_value", return_value=frappe._dict(parent="POS-INV-OTHER")):
			with self.assertRaisesRegex(frappe.ValidationError, "belong to the source POS Invoice"):
				self.ret.validate_return_line(frappe._dict(source_pos_invoice_item="ROW-1", qty=1))

	def test_requested_qty_must_fit_remaining_after_reservations(self):
		def get_value(doctype, name, fields, **kwargs):
			if doctype == "POS Invoice Item":
				return frappe._dict(parent="POS-INV-1", item_code="ITEM-1", qty=3, rate=12, warehouse="WH-1", rms_pos_order_item="ORDER-ITEM-1")
			if doctype == "POS Order Item":
				return frappe._dict(parent="ORDER-1", item="ITEM-1", warehouse="WH-1")
			if doctype == "POS Order":
				return frappe._dict(status="Paid", cashier_session="SESSION-1", store="STORE-1")
			if doctype == "UOM":
				return 0
			self.fail(f"Unexpected lookup: {doctype}")

		with patch("frappe.db.get_value", side_effect=get_value), patch.object(POSReturn, "get_reserved_qty", return_value=1):
			with self.assertRaisesRegex(frappe.ValidationError, "exceeds the sold quantity remaining"):
				self.ret.validate_return_line(frappe._dict(source_pos_invoice_item="ROW-1", qty=3))

	def test_valid_line_uses_server_item_rate_and_warehouse(self):
		def get_value(doctype, name, fields, **kwargs):
			if doctype == "POS Invoice Item":
				return frappe._dict(parent="POS-INV-1", item_code="ITEM-1", qty=3, rate=12, warehouse="WH-1", rms_pos_order_item="ORDER-ITEM-1")
			if doctype == "POS Order Item":
				return frappe._dict(parent="ORDER-1", item="ITEM-1", warehouse="WH-1")
			if doctype == "POS Order":
				return frappe._dict(status="Paid", cashier_session="SESSION-1", store="STORE-1")
			if doctype == "UOM":
				return 0
			self.fail(f"Unexpected lookup: {doctype}")

		row = frappe._dict(source_pos_invoice_item="ROW-1", qty=2, rate=0, amount=0, item_code="CLIENT-ITEM", warehouse="CLIENT-WH")
		with patch("frappe.db.get_value", side_effect=get_value), patch.object(POSReturn, "get_reserved_qty", return_value=0):
			self.ret.validate_return_line(row)

		self.assertEqual(row.item_code, "ITEM-1")
		self.assertEqual(row.rate, 12)
		self.assertEqual(row.amount, 24)
		self.assertEqual(row.warehouse, "WH-1")

	def test_saved_modifier_can_be_returned_as_its_own_invoice_line(self):
		def get_value(doctype, name, fields, **kwargs):
			if doctype == "POS Invoice Item":
				return frappe._dict(parent="POS-INV-1", item_code="MOD-1", qty=2, rate=3, warehouse="WH-1", rms_pos_order_item="ORDER-ITEM-1")
			if doctype == "POS Order Item":
				return frappe._dict(parent="ORDER-1", item="ITEM-1", warehouse="WH-1",
					modifiers='[{"item":"MOD-1","modifier_product":"MODIFIER-1"}]')
			if doctype == "POS Order":
				return frappe._dict(status="Paid", cashier_session="SESSION-1", store="STORE-1")
			if doctype == "UOM":
				return 0
			self.fail(f"Unexpected lookup: {doctype}")

		row = frappe._dict(source_pos_invoice_item="ROW-MOD", qty=1)
		with patch("frappe.db.get_value", side_effect=get_value), patch.object(POSReturn, "get_reserved_qty", return_value=0):
			self.ret.validate_return_line(row)
		self.assertEqual(row.item_code, "MOD-1")
		self.assertEqual(row.amount, 3)

	def test_partial_invoice_mapping_scales_actual_tax(self):
		source = frappe.new_doc("POS Invoice")
		source.append("items", {"amount": 50})
		source.append("items", {"amount": 50})
		source.append("taxes", {"idx": 1, "charge_type": "Actual", "tax_amount": 10})
		invoice = frappe.new_doc("POS Invoice")
		invoice.conversion_rate = 1
		invoice.append("items", {"pos_invoice_item": "ROW-1", "qty": -5, "stock_qty": -5,
			"rate": 10, "conversion_factor": 1, "amount": -50})
		invoice.append("items", {"pos_invoice_item": "ROW-2", "qty": -5, "stock_qty": -5,
			"rate": 10, "conversion_factor": 1, "amount": -50})
		invoice.append("taxes", {"idx": 1, "charge_type": "Actual", "tax_amount": -10})
		self.ret.append("items", {"source_pos_invoice_item": "ROW-1", "qty": 2})
		item_detail_lookup = Mock()
		invoice.set_missing_item_details = item_detail_lookup
		def make_return(source_invoice, target_doc):
			target_doc.set_missing_item_details()
			return invoice

		with patch("frappe.new_doc", return_value=invoice), \
				patch("erpnext.accounts.doctype.pos_invoice.pos_invoice.make_sales_return", side_effect=make_return), \
				patch("frappe.get_doc", return_value=source), patch.object(invoice, "calculate_taxes_and_totals"):
			result = self.ret.build_return_invoice()

		item_detail_lookup.assert_not_called()
		self.assertEqual(len(result.items), 1)
		self.assertEqual(result.items[0].pos_invoice_item, "ROW-1")
		self.assertEqual(result.items[0].qty, -2)
		self.assertEqual(result.taxes[0].tax_amount, -2)

	def test_stock_receipt_payload_excludes_waste(self):
		self.ret.items = [
			frappe._dict(is_waste=0, qty=2, source_pos_invoice_item="ROW-GOOD", pos_order_item="ORDER-ITEM"),
			frappe._dict(is_waste=1, qty=1, source_pos_invoice_item="ROW-WASTE", pos_order_item="ORDER-ITEM"),
		]
		def get_doc(doctype, name):
			if doctype == "POS Invoice Item":
				return frappe._dict(item_code="ITEM-1", qty=2, stock_uom="Nos", warehouse="WH-1")
			if doctype == "POS Order Item":
				return frappe._dict(selling_product="PRODUCT-1", parent="ORDER-1", recipe_snapshot="[]")
			if doctype == "Selling Product":
				return frappe._dict(name="PRODUCT-1", with_recipe=0, maintain_stock=1)
			if doctype == "POS Order":
				return frappe._dict(order_type="Dine In")
			self.fail(f"Unexpected document: {doctype}")

		def get_value(doctype, name, fieldname, **kwargs):
			if doctype == "Selling Product":
				return "PRODUCT-1"
			if doctype == "Order Type Account Mapping":
				return "COGS - ACME"
			if doctype == "Store":
				return "ACME"
			if doctype == "Item":
				return 1
			self.fail(f"Unexpected lookup: {doctype}")

		with patch("frappe.get_doc", side_effect=get_doc), patch("frappe.db.get_value", side_effect=get_value):
			items = self.ret.build_stock_receipt_items()
		self.assertEqual(items, [{"item": "ITEM-1", "qty": 2.0, "uom": "Nos",
			"warehouse": "WH-1", "expense_account": "COGS - ACME"}])

	def test_waste_recipe_receipt_uses_original_order_quantity_before_disposal(self):
		self.ret.is_waste = 1
		self.ret.append("items", {"source_pos_invoice_item": "SOURCE-1", "pos_order_item": "ORDER-ITEM-1", "qty": 1, "is_waste": 1})
		docs = {
			"POS Invoice Item": frappe._dict(item_code="MEAL", qty=3),
			"POS Order Item": frappe._dict(parent="ORDER-1", qty=4, recipe_snapshot='[{"item":"RICE","qty":2,"uom":"Kg","warehouse":"WH-1","source_selling_product":"PRODUCT-1"}]'),
			"Selling Product": frappe._dict(name="PRODUCT-1", with_recipe=1, maintain_stock=0),
			"POS Order": frappe._dict(order_type="Takeaway"),
		}
		with patch("frappe.get_doc", side_effect=lambda doctype, name: docs[doctype]), \
				patch("frappe.db.get_value", side_effect=lambda doctype,*args,**kwargs: {"Selling Product":"PRODUCT-1", "Store":"COMPANY", "Order Type Account Mapping":"COGS"}[doctype]):
			self.assertEqual(self.ret.build_stock_receipt_items(), [])
			items = self.ret.build_stock_receipt_items(include_waste=True)
		self.assertEqual(items[0]["qty"], .5)

	def test_recipe_modifier_return_scales_by_original_modifier_units(self):
		self.ret.append("items", {"source_pos_invoice_item":"MOD-LINE", "pos_order_item":"ORDER-LINE", "qty":1})
		docs = {"POS Invoice Item":frappe._dict(item_code="MOD",qty=6),
			"POS Order Item":frappe._dict(parent="ORDER-1",selling_product="MAIN",qty=4,
				modifiers='[{"modifier_product":"MOD-PRODUCT","item":"MOD","qty":2}]',
				recipe_snapshot='[{"item":"SAUCE-RAW","qty":0.8,"uom":"Kg","warehouse":"WH","source_selling_product":"MOD-PRODUCT"}]'),
			"Selling Product":frappe._dict(name="MOD-PRODUCT",with_recipe=1),"POS Order":frappe._dict(order_type="Takeaway")}
		with patch("frappe.get_doc",side_effect=lambda doctype,name:docs[doctype]), \
				patch("frappe.db.get_value",side_effect=lambda doctype,*args,**kwargs:{"Selling Product":"MOD-PRODUCT","Store":"COMPANY","Order Type Account Mapping":"COGS"}[doctype]):
			self.assertAlmostEqual(self.ret.build_stock_receipt_items()[0]["qty"],.1)

	def test_stock_return_converts_selling_units_to_stock_units(self):
		self.ret.append("items", {"source_pos_invoice_item": "SOURCE-1", "pos_order_item": "ORDER-ITEM-1", "qty": 2})
		docs = {"POS Invoice Item": frappe._dict(item_code="BOX", qty=3, stock_uom="Nos", warehouse="WH-1", conversion_factor=6),
			"POS Order Item": frappe._dict(parent="ORDER-1"), "Selling Product": frappe._dict(name="PRODUCT-1", with_recipe=0, maintain_stock=1),
			"POS Order": frappe._dict(order_type="Takeaway")}
		with patch("frappe.get_doc", side_effect=lambda doctype, name: docs[doctype]), \
				patch("frappe.db.get_value", side_effect=lambda doctype,*args,**kwargs: {"Selling Product":"PRODUCT-1", "Store":"COMPANY", "Order Type Account Mapping":"COGS", "Item":1}[doctype]):
			self.assertEqual(self.ret.build_stock_receipt_items()[0]["qty"],12)

	def test_failed_approval_rolls_back_credit_and_stock_movements(self):
		from rms.api.pos import approve_pos_return_document
		with patch("rms.api.pos._approve_pos_return_document", side_effect=frappe.ValidationError("Stock issue failed")), \
				patch("frappe.db.savepoint") as savepoint, patch("frappe.db.rollback") as rollback:
			with self.assertRaisesRegex(frappe.ValidationError, "Stock issue failed"):
				approve_pos_return_document(self.ret,"Administrator")
			savepoint.assert_called_once_with("rms_approve_pos_return")
			rollback.assert_called_once_with(save_point="rms_approve_pos_return")


class TestPOSReturnPermissions(unittest.TestCase):
	def test_cashier_list_query_is_limited_to_owned_requests(self):
		with patch("frappe.get_roles", return_value=["POS Cashier"]):
			condition = get_pos_return_permission_query("cashier@example.com")
		self.assertIn("`tabPOS Return`.owner", condition)
		self.assertIn("cashier@example.com", condition)

	def test_cashier_cannot_approve_a_return(self):
		with patch("frappe.session", frappe._dict(user="cashier@example.com")), patch("frappe.get_roles", return_value=["POS Cashier"]):
			with self.assertRaises(frappe.PermissionError):
				approve_pos_return("RETURN-1")

	def test_approved_return_retry_returns_existing_documents(self):
		ret = frappe._dict(name="RETURN-1", store="STORE-1", status="Approved",
			return_pos_invoice="CREDIT-1", stock_entry="STOCK-1", refund_total=28.5)
		with patch("frappe.session", frappe._dict(user="manager@example.com")), \
				patch("frappe.get_roles", return_value=["POS Manager"]), \
				patch("frappe.get_doc", return_value=ret), patch("rms.api.pos.assert_store_access"):
			result = approve_pos_return("RETURN-1")
		self.assertEqual(result, {"name": "RETURN-1", "status": "Approved",
			"return_pos_invoice": "CREDIT-1", "stock_entry": "STOCK-1", "waste_stock_entry": None, "refund_total": 28.5})
