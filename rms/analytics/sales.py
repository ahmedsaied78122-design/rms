"""Invoice-line accounting facts, with one allocation of tax and cash per invoice.

RMS links invoice rows to saved order lines. This also handles guest invoices and
credit notes without joining orders to invoice totals multiple times.
"""

from collections import defaultdict
from datetime import timedelta

from frappe import _
from frappe.utils import flt, getdate

from rms.analytics.catalog import GROUPS
from rms.utils import get_business_date_sql


def invoice_facts(ctx):
	return_day = get_business_date_sql("TIMESTAMP(pi.posting_date, pi.posting_time)", "s.operating_day_end")
	business_day = f"CASE WHEN pi.is_return = 1 THEN {return_day} ELSE o.business_date END"
	rows = ctx.query(f"""
		SELECT pi.name AS invoice, pi.is_return, pi.return_against, pi.posting_date,
		 pi.posting_time, pi.consolidated_invoice, pi.conversion_rate, pi.currency AS invoice_currency,
		 pi.base_net_total, pi.base_grand_total, pi.base_paid_amount, pi.base_change_amount,
		 pi.base_total_taxes_and_charges, pi.base_rounding_adjustment, pi.status AS invoice_status,
		 x.name AS invoice_item, x.item_code, x.item_name, x.qty, x.stock_qty, x.warehouse,
		 x.base_amount, x.base_net_amount, x.base_price_list_rate, x.base_rate,
		 x.pos_invoice_item AS source_invoice_item, quantities.absolute_qty,
		 o.name AS order_name, o.store, o.restaurant_brand AS brand, o.order_type,
		 pi.customer, pi.customer_name, pi.customer_group, o.dining_area, o.dining_table,
		 o.order_notes, o.recipe_stock_entry, o.cashier_session, cs.user AS cashier,
		 l.name AS order_item, l.selling_product AS parent_product, l.item AS parent_item,
		 l.qty AS order_qty, l.cancelled_qty, l.recipe_snapshot, l.modifiers, l.notes,
		 p.name AS product, p.title AS product_title, p.product_category AS category,
		 p.with_recipe, p.maintain_stock, p.uom, {business_day} AS business_date
		FROM `tabPOS Invoice` pi
		JOIN `tabPOS Invoice Item` x ON x.parent = pi.name AND x.parenttype = 'POS Invoice'
		LEFT JOIN `tabPOS Invoice Item` original ON original.name = x.pos_invoice_item
		JOIN `tabPOS Order Item` l ON l.name = COALESCE(NULLIF(x.rms_pos_order_item, ''), original.rms_pos_order_item)
		JOIN `tabPOS Order` o ON o.name = l.parent AND l.parenttype = 'POS Order'
		JOIN `tabStore` s ON s.name = o.store
		LEFT JOIN `tabCashier Session` cs ON cs.name = o.cashier_session
		LEFT JOIN `tabSelling Product` p ON p.item = x.item_code
		JOIN (SELECT parent, SUM(ABS(qty)) AS absolute_qty FROM `tabPOS Invoice Item`
		 WHERE parenttype = 'POS Invoice' GROUP BY parent) quantities ON quantities.parent = pi.name
		WHERE pi.docstatus = 1 AND pi.company = %(company)s AND o.store IN %(stores)s
		 AND {business_day} BETWEEN %(from_date)s AND %(to_date)s
		ORDER BY pi.posting_date, pi.posting_time, pi.name, x.idx
	""")
	result = []
	for raw in rows:
		r = normalize_fact(raw, ctx.currency)
		if (
			ctx.filters.include_returns is not None
			and not int(ctx.filters.include_returns)
			and r.get("is_return")
		):
			continue
		if ctx.accepts(r):
			result.append(r)
	if ctx.filters.business_period in {"today", "month"}:
		from rms.utils import get_business_date

		current = {store: get_business_date(store) for store in ctx.stores}
		result = [
			r
			for r in result
			if (
				getdate(r["business_date"]) == current[r["store"]]
				if ctx.filters.business_period == "today"
				else getdate(r["business_date"]).replace(day=1) == current[r["store"]].replace(day=1)
			)
		]
	return result


def normalize_fact(raw, currency):
	r = dict(raw)
	quantity = flt(r.get("qty"))
	weight = (
		flt(r.get("base_net_amount")) / flt(r["base_net_total"])
		if flt(r.get("base_net_total"))
		else abs(quantity) / (flt(r.get("absolute_qty")) or 1)
	)
	r["product"] = r.get("product") or r.get("parent_product")
	r["is_modifier"] = r.get("item_code") != r.get("parent_item")
	from rms.snapshots import parse_json_rows

	if r["is_modifier"] and not raw.get("product"):
		saved = next(
			(m for m in parse_json_rows(r.get("modifiers")) if m.get("item") == r.get("item_code")), None
		)
		r["product"] = saved.get("modifier_product") if saved else r.get("item_code")
	saved_components = parse_json_rows(r.get("recipe_snapshot"))
	if r.get("recipe_snapshot") is not None:
		r["with_recipe"] = int(
			any(c.get("source_selling_product") == r.get("product") for c in saved_components)
			or (
				not r["is_modifier"]
				and bool(saved_components)
				and not any(c.get("source_selling_product") for c in saved_components)
			)
		)
	r["quantity"] = quantity if not r["is_modifier"] else 0
	r["modifier_quantity"] = quantity if r["is_modifier"] else 0
	r["revenue"] = flt(r.get("base_net_amount"))
	r["gross_revenue"] = flt(r.get("base_amount"))
	r["allocated_discount"] = r["gross_revenue"] - r["revenue"]
	r["tax"] = flt(r.get("base_total_taxes_and_charges")) * weight
	r["invoice_total"] = flt(r.get("base_grand_total")) * weight
	r["collected"] = (flt(r.get("base_paid_amount")) - flt(r.get("base_change_amount"))) * weight
	r["rounding"] = flt(r.get("base_rounding_adjustment")) * weight
	r["sales_collected"] = 0 if r.get("is_return") else r["collected"]
	r["currency"] = currency
	r["sales_revenue"] = 0 if r.get("is_return") else r["revenue"]
	r["returned_revenue"] = -r["revenue"] if r.get("is_return") else 0
	return r


def dimension(row, group):
	date = getdate(row["business_date"])
	if group == "date":
		return str(date)
	if group == "week":
		return str(date - timedelta(days=date.weekday()))
	if group == "month":
		return date.strftime("%Y-%m")
	if group == "hour":
		return str(row.get("posting_time") or "00:00:00").split(":")[0].zfill(2) + ":00"
	if group == "invoice_product":
		return (row.get("invoice"), row.get("product"))
	return row.get(group) or ""


MEASURES = [
	"quantity",
	"modifier_quantity",
	"gross_revenue",
	"allocated_discount",
	"sales_revenue",
	"returned_revenue",
	"revenue",
	"tax",
	"invoice_total",
	"sales_collected",
	"collected",
	"rounding",
]


def aggregate(rows, group, currency):
	buckets = {}
	for row in rows:
		key = dimension(row, group)
		bucket = buckets.setdefault(
			key,
			{
				"group_key": key,
				"label": key if not isinstance(key, tuple) else key[1],
				"currency": currency,
				**{m: 0 for m in MEASURES},
				"_invoices": set(),
				"_returns": set(),
			},
		)
		bucket["_returns" if row.get("is_return") else "_invoices"].add(row["invoice"])
		for field in MEASURES:
			bucket[field] += flt(row.get(field))
		if group in {"product", "invoice_product"}:
			bucket["title"] = row.get("product_title") or row.get("item_name")
			bucket["category"] = row.get("category")
		if group == "invoice_product":
			bucket["invoice"] = key[0]
		if group == "invoice":
			for name in [
				"order_name",
				"store",
				"brand",
				"order_type",
				"customer",
				"cashier",
				"business_date",
			]:
				bucket[name] = row.get(name)
	for bucket in buckets.values():
		bucket["invoice_count"] = len(bucket.pop("_invoices"))
		bucket["return_count"] = len(bucket.pop("_returns"))
		bucket["average_invoice"] = (
			bucket["sales_collected"] / bucket["invoice_count"] if bucket["invoice_count"] else 0
		)
		bucket["discount_percent"] = (
			bucket["allocated_discount"] / bucket["gross_revenue"] * 100 if bucket["gross_revenue"] else 0
		)
	total = sum(r["revenue"] for r in buckets.values())
	for row in buckets.values():
		row["contribution"] = row["revenue"] / total * 100 if total else 0
	return sorted(buckets.values(), key=lambda r: str(r["group_key"]))


def col(field, label, kind="Currency", options=None, width=135):
	column = dict(fieldname=field, label=_(label), fieldtype=kind, width=width)
	if options:
		column["options"] = options
	elif kind == "Currency":
		column["options"] = "currency"
	return column


def columns(group, family="sales"):
	label, kind, options = GROUPS[group]
	result = [col("label", label, kind, options, 180)]
	if group == "invoice_product":
		result.insert(0, col("invoice", "Invoice", "Link", "POS Invoice", 180))
	if group in {"product", "invoice_product"}:
		result.extend(
			[
				col("title", "Product Name", "Data", width=190),
				col("category", "Product Category", "Link", "Product Category", 155),
			]
		)
	if group == "invoice":
		result.extend(
			[
				col("business_date", "Business Date", "Date"),
				col("store", "Store", "Link", "Store"),
				col("order_name", "Order", "Link", "POS Order"),
				col("customer", "Customer", "Link", "Customer"),
			]
		)
	result.extend(
		[
			col("invoice_count", "Sales Invoices", "Int"),
			col("return_count", "Credit Notes", "Int"),
			col("quantity", "Quantity Sold", "Float"),
			col("modifier_quantity", "Modifier Quantity", "Float"),
			col("gross_revenue", "Gross Revenue"),
			col("allocated_discount", "Allocated Discount"),
			col("revenue", "Net Revenue"),
			col("tax", "Taxes"),
			col("collected", "Net Collected"),
			col("rounding", "Rounding Difference"),
			col("average_invoice", "Average Invoice"),
			col("contribution", "Contribution %", "Percent"),
		]
	)
	return result


def summary(rows, currency):
	invoices = {r["invoice"] for r in rows if not r.get("is_return")}
	values = [
		("Net Revenue", sum(r["revenue"] for r in rows), "Currency"),
		("Taxes", sum(r["tax"] for r in rows), "Currency"),
		("Net Collected", sum(r["collected"] for r in rows), "Currency"),
		("Sales Invoices", len(invoices), "Int"),
	]
	return [
		dict(
			label=_(label),
			value=value,
			datatype=kind,
			currency=currency,
			indicator="Green" if value >= 0 else "Red",
		)
		for label, value, kind in values
	]


def chart(rows, measure="revenue", label="Net Revenue", kind="bar"):
	rows = [r for r in rows if r.get(measure) is not None]
	if kind in {"donut", "pie"} and any(flt(r.get(measure)) < 0 for r in rows):
		kind = "bar"
	plotted = (
		rows if kind == "line" else sorted(rows, key=lambda r: abs(flt(r.get(measure))), reverse=True)[:12]
	)
	return dict(
		data=dict(
			labels=[str(r.get("label") or _("Unassigned")) for r in plotted],
			datasets=[dict(name=_(label), values=[flt(r.get(measure)) for r in plotted])],
		),
		type=kind,
		colors=["#24785e", "#bed865", "#78aaa5", "#dc9c68"],
		height=240,
		animate=False,
		disableEntryAnimation=True,
	)


def payment_rows(ctx, facts):
	by_invoice = defaultdict(list)
	for r in facts:
		by_invoice[r["invoice"]].append(r)
	if not by_invoice:
		return []
	payments = ctx.query(
		"""SELECT pay.parent AS invoice, pay.mode_of_payment, pay.base_amount, pay.amount,
	 mode.type AS payment_type FROM `tabSales Invoice Payment` pay
	 LEFT JOIN `tabMode of Payment` mode ON mode.name = pay.mode_of_payment
	 WHERE pay.parenttype = 'POS Invoice' AND pay.parent IN %(invoices)s ORDER BY pay.parent, pay.idx""",
		{"invoices": list(by_invoice)},
	)
	by_method = {}
	change_left = {n: flt(rows[0].get("base_change_amount")) for n, rows in by_invoice.items()}
	# Return change from cash first, then from the last noncash tender if necessary.
	payments.sort(key=lambda p: (p.invoice, p.payment_type != "Cash"))
	for p in payments:
		matched = by_invoice[p.invoice]
		r = matched[0]
		amount = (
			flt(p.base_amount)
			if p.base_amount is not None
			else flt(p.amount) * flt(r.get("conversion_rate") or 1)
		)
		change = min(max(amount, 0), change_left[p.invoice])
		change_left[p.invoice] -= change
		amount -= change
		# Product/category filters retain the corresponding invoice share only.
		full = flt(r.get("base_net_total"))
		share = (
			sum(x["revenue"] for x in matched) / full
			if full
			else sum(abs(flt(x.get("qty"))) for x in matched) / (flt(r.get("absolute_qty")) or 1)
		)
		bucket = by_method.setdefault(
			p.mode_of_payment, dict(label=p.mode_of_payment, currency=ctx.currency, amount=0, _invoices=set())
		)
		bucket["amount"] += amount * share
		bucket["_invoices"].add(p.invoice)
	for b in by_method.values():
		b["invoice_count"] = len(b.pop("_invoices"))
	total = sum(b["amount"] for b in by_method.values())
	for b in by_method.values():
		b["contribution"] = b["amount"] / total * 100 if total else 0
	return list(by_method.values())
