import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate

from rms.utils import get_business_date_sql


def execute(filters=None):
	filters = frappe._dict(filters or {})
	roles = set(frappe.get_roles())
	if frappe.session.user == "Guest" or not (roles & {"POS Manager", "System Manager"}):
		frappe.throw(_("Only POS Managers can view sales reports."), frappe.PermissionError)
	if not filters.from_date or not filters.to_date:
		frappe.throw(_("Choose both a start and end date."))
	from_date, to_date = getdate(filters.from_date), getdate(filters.to_date)
	if from_date > to_date:
		frappe.throw(_("Start Date must be on or before End Date."))
	if date_diff(to_date, from_date) >= 90:
		frappe.throw(_("Choose a date range of 90 days or less."))

	base_values = {"from_date": from_date, "to_date": to_date, "user": frappe.session.user,
		"system_manager": int("System Manager" in roles)}
	filters_sql = {}
	for fieldname in ("store", "restaurant_brand", "order_type"):
		value = filters.get(fieldname)
		if value:
			filters_sql[fieldname] = value
			base_values[fieldname] = value
	return_business_date = get_business_date_sql("ret.approved_at", "store.operating_day_end")

	sales = frappe.db.sql(
		f"""
		SELECT o.business_date, o.store, o.restaurant_brand, o.order_type,
			COUNT(o.name) AS paid_orders, COALESCE(SUM(line_totals.qty_sold), 0) AS qty_sold,
			SUM(o.subtotal) AS subtotal, SUM(o.tax_total) AS tax_total,
			SUM(o.grand_total) AS gross_sales, 0 AS approved_returns,
			company.default_currency AS currency
		FROM `tabPOS Order` o
		LEFT JOIN (
			SELECT parent, SUM(qty) AS qty_sold FROM `tabPOS Order Item`
			WHERE parenttype = 'POS Order' GROUP BY parent
		) line_totals ON line_totals.parent = o.name
		INNER JOIN `tabStore` store ON store.name = o.store
		INNER JOIN `tabCompany` company ON company.name = store.company
		WHERE o.status = 'Paid'
			AND o.business_date BETWEEN %(from_date)s AND %(to_date)s
			AND (%(system_manager)s = 1 OR NOT EXISTS (
				SELECT 1 FROM `tabStore User Assignment` scope_check
				WHERE scope_check.parent = o.store AND scope_check.parenttype = 'Store' AND scope_check.enabled = 1
			) OR EXISTS (
				SELECT 1 FROM `tabStore User Assignment` scope_user
				WHERE scope_user.parent = o.store AND scope_user.parenttype = 'Store'
					AND scope_user.enabled = 1 AND scope_user.user = %(user)s
			))
			{self_filter_clause(filters_sql, "o")}
		GROUP BY o.business_date, o.store, o.restaurant_brand, o.order_type, company.default_currency
		""",
		base_values,
		as_dict=True,
	)

	returns = frappe.db.sql(
		f"""
		SELECT {return_business_date} AS business_date, ret.store, o.restaurant_brand, o.order_type,
			0 AS paid_orders, 0 AS qty_sold, 0 AS subtotal, 0 AS tax_total, 0 AS gross_sales,
			SUM(ret.refund_total) AS approved_returns, company.default_currency AS currency
		FROM `tabPOS Return` ret
		INNER JOIN `tabPOS Order` o ON o.pos_invoice = ret.source_pos_invoice
			AND o.cashier_session = ret.cashier_session
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
			{self_filter_clause(filters_sql, "o")}
		GROUP BY {return_business_date}, ret.store, o.restaurant_brand, o.order_type, company.default_currency
		""",
		base_values,
		as_dict=True,
	)

	data = merge_sales_and_returns(sales, returns)
	columns = [
		{"fieldname": "business_date", "label": _("Business Date"), "fieldtype": "Date", "width": 110},
		{"fieldname": "store", "label": _("Store"), "fieldtype": "Link", "options": "Store", "width": 140},
		{"fieldname": "restaurant_brand", "label": _("Brand"), "fieldtype": "Link", "options": "Restaurant Brand", "width": 140},
		{"fieldname": "order_type", "label": _("Order Type"), "fieldtype": "Link", "options": "Order Type", "width": 140},
		{"fieldname": "paid_orders", "label": _("Paid Orders"), "fieldtype": "Int", "width": 100},
		{"fieldname": "qty_sold", "label": _("Quantity Sold"), "fieldtype": "Float", "width": 110},
		{"fieldname": "subtotal", "label": _("Subtotal"), "fieldtype": "Currency", "options": "currency", "width": 125},
		{"fieldname": "tax_total", "label": _("Taxes"), "fieldtype": "Currency", "options": "currency", "width": 110},
		{"fieldname": "gross_sales", "label": _("Gross Sales"), "fieldtype": "Currency", "options": "currency", "width": 125},
		{"fieldname": "approved_returns", "label": _("Approved Returns"), "fieldtype": "Currency", "options": "currency", "width": 135},
		{"fieldname": "net_sales", "label": _("Net Sales"), "fieldtype": "Currency", "options": "currency", "width": 125},
		{"fieldname": "currency", "label": _("Currency"), "fieldtype": "Link", "options": "Currency", "width": 90},
	]
	return columns, data


def self_filter_clause(filters, order_alias):
	if not filters:
		return ""
	clauses = [f"{order_alias}.{fieldname} = %({fieldname})s" for fieldname in filters]
	return " AND " + " AND ".join(clauses)


def merge_sales_and_returns(sales, returns):
	combined = {}
	for row in sales:
		key = (row.business_date, row.store, row.restaurant_brand, row.order_type, row.currency)
		combined[key] = {**row, "approved_returns": 0, "net_sales": flt(row.gross_sales)}
	for row in returns:
		key = (row.business_date, row.store, row.restaurant_brand, row.order_type, row.currency)
		item = combined.setdefault(key, {**row, "paid_orders": 0, "qty_sold": 0, "subtotal": 0,
			"tax_total": 0, "gross_sales": 0})
		item["approved_returns"] = flt(item.get("approved_returns")) + flt(row.approved_returns)
		item["net_sales"] = flt(item.get("gross_sales")) - item["approved_returns"]
	return sorted(combined.values(), key=lambda row: (row["business_date"], row["store"], row["restaurant_brand"], row["order_type"]))
