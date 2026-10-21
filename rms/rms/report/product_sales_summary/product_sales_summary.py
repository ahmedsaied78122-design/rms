import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate

from rms.utils import get_business_date_sql


def execute(filters=None):
	filters = frappe._dict(filters or {})
	roles = set(frappe.get_roles())
	if frappe.session.user == "Guest" or not (roles & {"POS Manager", "System Manager"}):
		frappe.throw(_("Only POS Managers can view product sales reports."), frappe.PermissionError)
	if not filters.from_date or not filters.to_date:
		frappe.throw(_("Choose both a start and end date."))
	from_date, to_date = getdate(filters.from_date), getdate(filters.to_date)
	if from_date > to_date:
		frappe.throw(_("Start Date must be on or before End Date."))
	if date_diff(to_date, from_date) >= 90:
		frappe.throw(_("Choose a date range of 90 days or less."))

	values = {"from_date": from_date, "to_date": to_date, "user": frappe.session.user,
		"system_manager": int("System Manager" in roles)}
	filters_sql = {}
	for fieldname in ("store", "restaurant_brand", "selling_product"):
		value = filters.get(fieldname)
		if value:
			filters_sql[fieldname] = value
			values[fieldname] = value
	filter_clause = " AND " + " AND ".join(f"o.{fieldname} = %({fieldname})s" if fieldname != "selling_product"
		else f"product.name = %({fieldname})s" for fieldname in filters_sql) if filters_sql else ""
	return_business_date = get_business_date_sql("ret.approved_at", "store.operating_day_end")
	
	sales = frappe.db.sql(
		f"""
		SELECT o.business_date, o.store, o.restaurant_brand, product.name AS selling_product,
			product.title AS product_title, sale_line.item_code,
			SUM(sale_line.qty) AS qty_sold, 0 AS qty_returned,
			SUM(sale_line.amount) AS gross_sales, 0 AS returned_amount,
			company.default_currency AS currency
		FROM `tabPOS Invoice Item` sale_line
		INNER JOIN `tabPOS Invoice` invoice ON invoice.name = sale_line.parent
			AND sale_line.parenttype = 'POS Invoice' AND invoice.docstatus = 1 AND invoice.is_return = 0
		INNER JOIN `tabPOS Order Item` order_item ON order_item.name = sale_line.rms_pos_order_item
		INNER JOIN `tabPOS Order` o ON o.name = order_item.parent AND o.status = 'Paid'
		INNER JOIN `tabSelling Product` product ON product.item = sale_line.item_code
		INNER JOIN `tabStore` store ON store.name = o.store
		INNER JOIN `tabCompany` company ON company.name = store.company
		WHERE o.business_date BETWEEN %(from_date)s AND %(to_date)s
			AND (%(system_manager)s = 1 OR NOT EXISTS (
				SELECT 1 FROM `tabStore User Assignment` scope_check
				WHERE scope_check.parent = o.store AND scope_check.parenttype = 'Store' AND scope_check.enabled = 1
			) OR EXISTS (
				SELECT 1 FROM `tabStore User Assignment` scope_user
				WHERE scope_user.parent = o.store AND scope_user.parenttype = 'Store'
					AND scope_user.enabled = 1 AND scope_user.user = %(user)s
			))
			{filter_clause}
		GROUP BY o.business_date, o.store, o.restaurant_brand, product.name, product.title,
			sale_line.item_code, company.default_currency
		""",
		values,
		as_dict=True,
	)

	returns = frappe.db.sql(
		f"""
		SELECT {return_business_date} AS business_date, ret.store, o.restaurant_brand,
			product.name AS selling_product, product.title AS product_title, source_line.item_code,
			0 AS qty_sold, SUM(ret_item.qty) AS qty_returned, 0 AS gross_sales,
			SUM(ret_item.amount) AS returned_amount, company.default_currency AS currency
		FROM `tabPOS Return` ret
		INNER JOIN `tabPOS Return Item` ret_item ON ret_item.parent = ret.name
			AND ret_item.parenttype = 'POS Return'
		INNER JOIN `tabPOS Invoice Item` source_line ON source_line.name = ret_item.source_pos_invoice_item
		INNER JOIN `tabPOS Order Item` order_item ON order_item.name = ret_item.pos_order_item
		INNER JOIN `tabPOS Order` o ON o.name = order_item.parent
		INNER JOIN `tabSelling Product` product ON product.item = source_line.item_code
		INNER JOIN `tabStore` store ON store.name = ret.store
		INNER JOIN `tabCompany` company ON company.name = store.company
		WHERE ret.status = 'Approved' AND ret.docstatus < 2
			AND {return_business_date} BETWEEN %(from_date)s AND %(to_date)s
			AND (%(system_manager)s = 1 OR NOT EXISTS (
				SELECT 1 FROM `tabStore User Assignment` scope_check
				WHERE scope_check.parent = ret.store AND scope_check.parenttype = 'Store' AND scope_check.enabled = 1
			) OR EXISTS (
				SELECT 1 FROM `tabStore User Assignment` scope_user
				WHERE scope_user.parent = ret.store AND scope_user.parenttype = 'Store'
					AND scope_user.enabled = 1 AND scope_user.user = %(user)s
			))
			{filter_clause}
		GROUP BY {return_business_date}, ret.store, o.restaurant_brand, product.name,
			product.title, source_line.item_code, company.default_currency
		""",
		values,
		as_dict=True,
	)

	data = merge_product_rows(sales, returns)
	columns = [
		{"fieldname": "business_date", "label": _("Business Date"), "fieldtype": "Date", "width": 110},
		{"fieldname": "store", "label": _("Store"), "fieldtype": "Link", "options": "Store", "width": 135},
		{"fieldname": "restaurant_brand", "label": _("Brand"), "fieldtype": "Link", "options": "Restaurant Brand", "width": 135},
		{"fieldname": "selling_product", "label": _("Selling Product"), "fieldtype": "Link", "options": "Selling Product", "width": 175},
		{"fieldname": "product_title", "label": _("Product"), "fieldtype": "Data", "width": 175},
		{"fieldname": "item_code", "label": _("ERPNext Item"), "fieldtype": "Link", "options": "Item", "width": 150},
		{"fieldname": "qty_sold", "label": _("Quantity Sold"), "fieldtype": "Float", "width": 105},
		{"fieldname": "qty_returned", "label": _("Quantity Returned"), "fieldtype": "Float", "width": 125},
		{"fieldname": "net_qty", "label": _("Net Quantity"), "fieldtype": "Float", "width": 105},
		{"fieldname": "gross_sales", "label": _("Gross Sales"), "fieldtype": "Currency", "options": "currency", "width": 125},
		{"fieldname": "returned_amount", "label": _("Returns"), "fieldtype": "Currency", "options": "currency", "width": 115},
		{"fieldname": "net_sales", "label": _("Net Sales"), "fieldtype": "Currency", "options": "currency", "width": 125},
		{"fieldname": "currency", "label": _("Currency"), "fieldtype": "Link", "options": "Currency", "width": 90},
	]
	return columns, data


def merge_product_rows(sales, returns):
	combined = {}
	for row in sales:
		key = product_row_key(row)
		combined[key] = {**row, "qty_returned": 0, "returned_amount": 0,
			"net_qty": flt(row.qty_sold), "net_sales": flt(row.gross_sales)}
	for row in returns:
		key = product_row_key(row)
		item = combined.setdefault(key, {**row, "qty_sold": 0, "gross_sales": 0,
			"qty_returned": 0, "returned_amount": 0, "net_qty": 0, "net_sales": 0})
		item["qty_returned"] = flt(item.get("qty_returned")) + flt(row.qty_returned)
		item["returned_amount"] = flt(item.get("returned_amount")) + flt(row.returned_amount)
		item["net_qty"] = flt(item.get("qty_sold")) - item["qty_returned"]
		item["net_sales"] = flt(item.get("gross_sales")) - item["returned_amount"]
	return sorted(combined.values(), key=lambda row: (row["business_date"], row["store"], row["product_title"]))


def product_row_key(row):
	return (row.business_date, row.store, row.restaurant_brand, row.selling_product, row.item_code, row.currency)
