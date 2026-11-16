"""Operational reporting from saved RMS state and its durable event timestamps."""

from collections import defaultdict
from datetime import datetime, time, timedelta
import json

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime

from rms.analytics.context import names
from rms.analytics.sales import col


def order_rows(ctx):
	rows = ctx.query("""SELECT o.name AS order_name,o.status,o.store,o.restaurant_brand AS brand,
	 o.order_type,o.customer,o.dining_area,o.dining_table,o.table_check_group,o.business_date,
	 o.order_notes,o.creation,o.modified,o.grand_total,o.pos_invoice,cs.user AS cashier,
	 (SELECT MAX(TIMESTAMP(pi.posting_date,pi.posting_time)) FROM `tabPOS Invoice` pi
	 JOIN `tabPOS Invoice Item` pii ON pii.parent=pi.name
	 JOIN `tabPOS Order Item` oi ON oi.name=pii.rms_pos_order_item
	 WHERE oi.parent=o.name AND oi.parenttype='POS Order' AND pi.docstatus=1 AND pi.is_return=0) AS last_payment_at
	 FROM `tabPOS Order` o JOIN `tabStore` s ON s.name=o.store
	 LEFT JOIN `tabCashier Session` cs ON cs.name=o.cashier_session
	 WHERE s.company=%(company)s AND o.store IN %(stores)s
	 AND o.business_date BETWEEN %(from_date)s AND %(to_date)s ORDER BY o.creation""")
	return [dict(r) for r in rows if ctx.accepts(r)]


def notes(ctx):
	orders = order_rows(ctx)
	if not orders:
		return [], []
	lines = ctx.query(
		"""SELECT parent AS order_name,selling_product AS product,notes,qty
	 FROM `tabPOS Order Item` WHERE parenttype='POS Order' AND parent IN %(orders)s
	 AND COALESCE(notes,'') != ''""",
		{"orders": [r["order_name"] for r in orders]},
	)
	by_order = {r["order_name"]: r for r in orders}
	result = [
		{**r, "notes": r["order_notes"], "note_scope": _("Order"), "currency": ctx.currency}
		for r in orders
		if r.get("order_notes")
	]
	for row in lines:
		r = {**by_order[row.order_name], **row, "note_scope": _("Item"), "currency": ctx.currency}
		if ctx.accepts(r):
			result.append(r)
	return [
		col("order_name", "Order", "Link", "POS Order", 180),
		col("business_date", "Business Date", "Date"),
		col("store", "Store", "Link", "Store"),
		col("note_scope", "Note Scope", "Data"),
		col("product", "Selling Product", "Link", "Selling Product"),
		col("notes", "Notes", "Data", width=330),
	], result


def cancellations(ctx):
	rows = ctx.query("""SELECT c.name,c.parent AS order_name,oi.selling_product AS product,c.qty,
	 c.reason,c.comment,c.cancelled_by,c.cancelled_at,c.is_waste,c.waste_stock_entry AS stock_entry,
	 o.store,o.restaurant_brand AS brand,o.order_type,o.customer,o.dining_table,o.dining_area,
	 p.product_category AS category,p.title AS product_title,s.company,COALESCE(pl.currency,company.default_currency) AS currency,
	 oi.selling_price,oi.modifiers
	 FROM `tabPOS Order Item Cancellation` c JOIN `tabPOS Order` o ON o.name=c.parent
	 JOIN `tabPOS Order Item` oi ON oi.name=c.pos_order_item
	 JOIN `tabStore` s ON s.name=o.store JOIN `tabCompany` company ON company.name=s.company
	 LEFT JOIN `tabSelling Product` p ON p.name=oi.selling_product
	 LEFT JOIN `tabPrice List` pl ON pl.name=oi.price_list
	 WHERE c.parenttype='POS Order' AND s.company=%(company)s AND o.store IN %(stores)s
	 AND c.cancelled_at >= %(start)s AND c.cancelled_at < %(end)s ORDER BY c.cancelled_at DESC""")
	result = []
	for r in rows:
		if ctx.accepts(r):
			from rms.rms.doctype.pos_order.pos_order import calculate_order_item_amount
			from rms.snapshots import parse_json_rows

			r["cancelled_value"] = calculate_order_item_amount(
				r.qty, r.selling_price, parse_json_rows(r.modifiers)
			)
			result.append(dict(r))
	return [
		col("cancelled_at", "Cancelled At", "Datetime", width=170),
		col("order_name", "Order", "Link", "POS Order", 180),
		col("store", "Store", "Link", "Store"),
		col("product", "Selling Product", "Link", "Selling Product", 180),
		col("qty", "Cancelled Quantity", "Float"),
		col("cancelled_value", "Cancelled Item Value"),
		col("is_waste", "Waste", "Check"),
		col("reason", "Reason", "Data", width=200),
		col("comment", "Comment", "Data", width=200),
		col("cancelled_by", "Cancelled By", "Link", "User"),
		col("stock_entry", "Stock Entry", "Link", "Stock Entry"),
	], result


def returns(ctx):
	rows = ctx.query("""SELECT ret.name AS return_name,ret.source_pos_invoice,ret.return_pos_invoice,
	 ret.store,ret.customer,ret.status,ret.refund_total,ret.is_waste,ret.reason,ret.comment,
	 ret.approved_by,ret.approved_at,ret.creation,ret.stock_entry,company.default_currency AS currency,
	 o.restaurant_brand AS brand,o.order_type,o.dining_area,o.dining_table,
	 ri.item_code,ri.qty,ri.rate,ri.amount,COALESCE(totals.total_amount,0) AS total_amount,COALESCE(totals.total_qty,0) AS total_qty,COALESCE(credit.conversion_rate,original.conversion_rate,1) AS conversion_rate,p.name AS product,p.product_category AS category
	 FROM `tabPOS Return` ret JOIN `tabPOS Return Item` ri ON ri.parent=ret.name
	 LEFT JOIN (SELECT parent,SUM(amount) AS total_amount,SUM(ABS(qty)) AS total_qty FROM `tabPOS Return Item` GROUP BY parent) totals ON totals.parent=ret.name
	 LEFT JOIN `tabPOS Invoice` credit ON credit.name=ret.return_pos_invoice
	 LEFT JOIN `tabPOS Invoice` original ON original.name=ret.source_pos_invoice
	 JOIN `tabPOS Order Item` oi ON oi.name=ri.pos_order_item
	 JOIN `tabPOS Order` o ON o.name=oi.parent
	 JOIN `tabStore` s ON s.name=ret.store JOIN `tabCompany` company ON company.name=s.company
	 LEFT JOIN `tabSelling Product` p ON p.item=ri.item_code
	 WHERE ret.docstatus < 2 AND s.company=%(company)s AND ret.store IN %(stores)s
	 AND COALESCE(ret.approved_at,ret.creation) >= %(start)s
	 AND COALESCE(ret.approved_at,ret.creation) < %(end)s ORDER BY ret.creation DESC""")
	result = [
		dict(r) for r in rows if ctx.accepts(r) and (not ctx.filters.status or r.status == ctx.filters.status)
	]
	# Refund_total belongs to the document, not each returned line.
	for r in result:
		total = flt(r.pop("total_amount", 0))
		total_qty = flt(r.pop("total_qty", 0))
		weight = flt(r["amount"]) / total if total else abs(flt(r["qty"])) / total_qty if total_qty else 0
		r["allocated_refund"] = flt(r.pop("refund_total", 0)) * flt(r["conversion_rate"]) * weight
		r["amount"] = flt(r["amount"]) * flt(r["conversion_rate"])
	return [
		col("return_name", "Return", "Link", "POS Return", 180),
		col("source_pos_invoice", "Original Invoice", "Link", "POS Invoice", 180),
		col("return_pos_invoice", "Credit Note", "Link", "POS Invoice", 180),
		col("status", "Status", "Data"),
		col("approved_at", "Approved At", "Datetime"),
		col("store", "Store", "Link", "Store"),
		col("customer", "Customer", "Link", "Customer"),
		col("product", "Selling Product", "Link", "Selling Product", 170),
		col("qty", "Returned Quantity", "Float"),
		col("amount", "Returned Line Value"),
		col("allocated_refund", "Allocated Refund"),
		col("is_waste", "Waste", "Check"),
		col("approved_by", "Approved By", "Link", "User"),
		col("reason", "Reason", "Data", width=220),
	], result


def kitchen(ctx):
	rows = ctx.query("""SELECT k.name AS ticket,k.pos_order AS order_name,k.store,k.preparation_area,k.status,
	 k.sent_at,k.started_at,k.ready_at,k.picked_at,oi.selling_product AS product,
	 p.product_category AS category,ki.qty,ki.cancelled_qty,
	 o.restaurant_brand AS brand,o.order_type,o.customer,o.dining_area,o.dining_table,
	 cs.user AS cashier FROM `tabKitchen Ticket` k
	 JOIN `tabKitchen Ticket Item` ki ON ki.parent=k.name
	 JOIN `tabPOS Order Item` oi ON oi.name=ki.pos_order_item
	 JOIN `tabPOS Order` o ON o.name=k.pos_order
	 LEFT JOIN `tabCashier Session` cs ON cs.name=o.cashier_session
	 LEFT JOIN `tabSelling Product` p ON p.name=oi.selling_product
	 JOIN `tabStore` s ON s.name=k.store
	 WHERE s.company=%(company)s AND k.store IN %(stores)s AND k.is_item_cancellation_notice=0
	 AND k.sent_at >= %(start)s AND k.sent_at < %(end)s""")
	groups = {}
	target = flt(ctx.filters.target_minutes)
	if target < 0:
		frappe.throw(_("Target minutes must be zero or greater."))
	allowed_areas = names(ctx.filters.preparation_area)
	for r in rows:
		if not ctx.accepts(r) or (allowed_areas and r.preparation_area not in allowed_areas):
			continue
		key = (r.store, r.preparation_area)
		g = groups.setdefault(
			key,
			dict(
				store=r.store,
				preparation_area=r.preparation_area,
				quantity=0,
				_tickets={},
				currency=ctx.currency,
			),
		)
		g["quantity"] += max(flt(r.qty) - flt(r.cancelled_qty), 0)
		g["_tickets"][r.ticket] = r
	result = []
	for g in groups.values():
		tickets = list(g.pop("_tickets").values())
		g["tickets"] = len(tickets)
		g["ready_tickets"] = sum(r.status in {"Ready", "Picked"} for r in tickets)
		g["cancelled_tickets"] = sum(r.status == "Cancelled" for r in tickets)
		for field, start, end in [
			("queue_minutes", "sent_at", "started_at"),
			("prep_minutes", "started_at", "ready_at"),
			("handoff_minutes", "ready_at", "picked_at"),
		]:
			values = [
				max((get_datetime(r[end]) - get_datetime(r[start])).total_seconds() / 60, 0)
				for r in tickets
				if r.get(start) and r.get(end)
			]
			g[field] = sum(values) / len(values) if values else None
		g["delayed_tickets"] = (
			sum(
				1
				for r in tickets
				if r.started_at
				and r.ready_at
				and (get_datetime(r.ready_at) - get_datetime(r.started_at)).total_seconds() / 60 > target
			)
			if target
			else None
		)
		result.append(g)
	return [
		col("store", "Store", "Link", "Store"),
		col("preparation_area", "Preparation Area", "Link", "Preparation Area", 180),
		col("tickets", "Kitchen Tickets", "Int"),
		col("quantity", "Quantity", "Float"),
		col("ready_tickets", "Ready Tickets", "Int"),
		col("cancelled_tickets", "Cancelled Tickets", "Int"),
		col("queue_minutes", "Average Queue Minutes", "Float"),
		col("prep_minutes", "Average Preparation Minutes", "Float"),
		col("handoff_minutes", "Average Handoff Minutes", "Float"),
		col("delayed_tickets", "Tickets Above Analysis Target", "Int"),
	], result


def printing(ctx):
	rows = ctx.query("""SELECT j.print_device,j.store,j.status,j.attempt_count,j.printed_at,j.queued_at
	 FROM `tabPrint Dispatch Job` j JOIN `tabStore` s ON s.name=j.store
	 WHERE s.company=%(company)s AND j.store IN %(stores)s
	 AND j.queued_at >= %(start)s AND j.queued_at < %(end)s""")
	groups = {}
	for r in rows:
		if ctx.filters.print_device and r.print_device != ctx.filters.print_device:
			continue
		g = groups.setdefault(
			(r.store, r.print_device),
			dict(
				store=r.store,
				print_device=r.print_device,
				jobs=0,
				printed=0,
				failed=0,
				attempts=0,
				currency=ctx.currency,
			),
		)
		g["jobs"] += 1
		g["printed"] += int(r.status == "Printed")
		g["failed"] += int(r.status == "Failed")
		g["attempts"] += cint(r.attempt_count)
	return [
		col("store", "Store", "Link", "Store"),
		col("print_device", "Print Device", "Link", "Print Device", 190),
		col("jobs", "Print Jobs", "Int"),
		col("printed", "Printed Receipts", "Int"),
		col("failed", "Failed Jobs", "Int"),
		col("attempts", "Attempts", "Int"),
	], list(groups.values())


def union_windows(windows):
	merged = []
	for start, end in sorted((s, e) for s, e in windows if e > s):
		if merged and start <= merged[-1][1]:
			merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
		else:
			merged.append((start, end))
	return merged


def overlap_minutes(left, right):
	return sum(
		max(0, (min(a_end, b_end) - max(a_start, b_start)).total_seconds() / 60)
		for a_start, a_end in union_windows(left)
		for b_start, b_end in union_windows(right)
	)


def _time(value):
	if isinstance(value, timedelta):
		return (datetime.min + value).time()
	if isinstance(value, time):
		return value
	return datetime.strptime(str(value).split(".")[0], "%H:%M:%S").time()


def working_windows(rows, start, end):
	result = []
	day = start.date() - timedelta(days=1)
	while day <= end.date():
		for row in rows:
			if not row.get("enabled") or row.get("weekday") != day.strftime("%A"):
				continue
			opening = datetime.combine(day, _time(row["from_time"]))
			closing = datetime.combine(day, _time(row["to_time"]))
			if closing <= opening:
				closing += timedelta(days=1)
			result.append((max(opening, start), min(closing, end)))
		day += timedelta(days=1)
	return union_windows(result)


def occupancy(ctx):
	# Include orders opened before the period that were still occupying a table.
	rows = ctx.query("""SELECT o.name AS order_name,o.store,o.dining_area,o.dining_table,o.creation,
	 o.status,o.restaurant_brand AS brand,o.order_type,o.customer,o.table_check_group,
	 MAX(CASE WHEN pi.is_return=0 AND pi.docstatus=1 THEN TIMESTAMP(pi.posting_date,pi.posting_time) END) AS last_payment_at
	 FROM `tabPOS Order` o JOIN `tabStore` s ON s.name=o.store
	 LEFT JOIN `tabPOS Order Item` oi ON oi.parent=o.name AND oi.parenttype='POS Order'
	 LEFT JOIN `tabPOS Invoice Item` pii ON pii.rms_pos_order_item=oi.name
	 LEFT JOIN `tabPOS Invoice` pi ON pi.name=pii.parent
	 WHERE s.company=%(company)s AND o.store IN %(stores)s AND o.creation < %(end)s
	 GROUP BY o.name HAVING o.status NOT IN ('Paid','Cancelled') OR last_payment_at >= %(start)s OR o.status='Cancelled'""")
	versions = []
	cancelled = [r.order_name for r in rows if r.status == "Cancelled"]
	if cancelled:
		versions = ctx.query(
			"""SELECT docname,creation,data FROM `tabVersion`
	 WHERE ref_doctype='POS Order' AND docname IN %(orders)s ORDER BY creation""",
			{"orders": cancelled},
		)
	closed = {}
	for event in versions:
		try:
			changes = json.loads(event.data or "{}").get("changed", [])
		except ValueError:
			continue
		if any(len(c) >= 3 and c[0] == "status" and c[2] == "Cancelled" for c in changes):
			closed.setdefault(event.docname, event.creation)
	tables = ctx.query("""SELECT t.name AS dining_table,t.title,t.store,t.dining_area FROM `tabDining Table` t
	 JOIN `tabStore` s ON s.name=t.store WHERE s.company=%(company)s AND t.store IN %(stores)s""")
	schedules = defaultdict(list)
	if cint(ctx.filters.working_hours_only):
		for row in ctx.query("""SELECT parent,weekday,from_time,to_time,order_type,enabled FROM `tabStore Working Hour`
		 WHERE parenttype='Store' AND parent IN %(stores)s"""):
			if not ctx.filters.order_type or row.order_type in (None, "", ctx.filters.order_type):
				schedules[row.parent].append(row)
	end = min(ctx.end, now_datetime())
	busy = defaultdict(list)
	turnovers = defaultdict(set)
	unknown = defaultdict(int)
	for r in rows:
		if not r.dining_table or not ctx.accepts(r):
			continue
		finish = (
			r.last_payment_at
			if r.status == "Paid"
			else closed.get(r.order_name)
			if r.status == "Cancelled"
			else end
		)
		if not finish:
			unknown[r.dining_table] += 1
			continue
		start = max(get_datetime(r.creation), ctx.start)
		finish = min(get_datetime(finish), end)
		if finish > start:
			busy[r.dining_table].append((start, finish))
			turnovers[r.dining_table].add(r.table_check_group or r.order_name)
	result = []
	for t in tables:
		if names(ctx.filters.dining_table) and t.dining_table not in names(ctx.filters.dining_table):
			continue
		if names(ctx.filters.dining_area) and t.dining_area not in names(ctx.filters.dining_area):
			continue
		windows = (
			working_windows(schedules[t.store], ctx.start, end)
			if cint(ctx.filters.working_hours_only)
			else [(ctx.start, end)]
		)
		available = sum((e - s).total_seconds() / 60 for s, e in windows if e > s)
		occupied = overlap_minutes(busy[t.dining_table], windows)
		result.append(
			{
				**t,
				"working_minutes": available,
				"busy_minutes": occupied,
				"utilization_percent": occupied / available * 100 if available else None,
				"turnovers": len(turnovers[t.dining_table]),
				"untracked_closures": unknown[t.dining_table],
			}
		)
	return [
		col("dining_table", "Dining Table", "Link", "Dining Table", 170),
		col("title", "Table Name", "Data"),
		col("store", "Store", "Link", "Store"),
		col("dining_area", "Dining Area", "Link", "Dining Area"),
		col("working_minutes", "Available Minutes", "Float"),
		col("busy_minutes", "Occupied Minutes", "Float"),
		col("utilization_percent", "Utilization %", "Percent"),
		col("turnovers", "Table Visits", "Int"),
		col("untracked_closures", "Missing Closing Timestamps", "Int"),
	], result
