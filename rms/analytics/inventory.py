"""Inventory and purchasing facts from submitted native ERP documents."""

import frappe
from frappe import _
from frappe.utils import cint, flt

from rms.analytics.context import names
from rms.analytics.sales import col


def matches_item(ctx, row):
	if names(ctx.filters.item) and row.get("item") not in names(ctx.filters.item):
		return False
	if ctx.filters.item_group:
		if not hasattr(ctx, "_item_groups"):
			bounds = frappe.db.get_value("Item Group", ctx.filters.item_group, ["lft", "rgt"], as_dict=True)
			if not bounds:
				frappe.throw(_("Choose an existing Item Group."))
			ctx._item_groups = set(
				frappe.get_all(
					"Item Group", filters={"lft": [">=", bounds.lft], "rgt": ["<=", bounds.rgt]}, pluck="name"
				)
			)
		if row.get("item_group") not in ctx._item_groups:
			return False
	return True


def conditions(ctx, alias="sle"):
	warehouses = ctx.warehouse_scope()
	values = {"warehouses": warehouses or [""]}
	where = [
		f"{alias}.company=%(company)s",
		f"{alias}.warehouse IN %(warehouses)s",
		f"{alias}.is_cancelled=0",
	]
	items = names(ctx.filters.item)
	if items:
		where.append(f"{alias}.item_code IN %(items)s")
		values["items"] = items
	if ctx.filters.item_group:
		bounds = frappe.db.get_value("Item Group", ctx.filters.item_group, ["lft", "rgt"], as_dict=True)
		if not bounds:
			frappe.throw(_("Choose an existing Item Group."))
		where.append(
			f"{alias}.item_code IN (SELECT i.name FROM `tabItem` i JOIN `tabItem Group` ig ON ig.name=i.item_group WHERE ig.lft >= %(left)s AND ig.rgt <= %(right)s)"
		)
		values.update(left=bounds.lft, right=bounds.rgt)
	return " AND ".join(where), values


def movement(ctx):
	where, values = conditions(ctx)
	rows = ctx.query(
		f"""SELECT sle.item_code AS item,i.item_name,i.item_group,i.stock_uom AS uom,
	 sle.warehouse,
	 SUM(CASE WHEN sle.posting_date < %(from_date)s THEN sle.actual_qty ELSE 0 END) AS opening_qty,
	 SUM(CASE WHEN sle.posting_date < %(from_date)s THEN sle.stock_value_difference ELSE 0 END) AS opening_value,
	 SUM(CASE WHEN sle.posting_date >= %(from_date)s AND sle.actual_qty > 0 THEN sle.actual_qty ELSE 0 END) AS incoming_qty,
	 SUM(CASE WHEN sle.posting_date >= %(from_date)s AND sle.actual_qty < 0 THEN -sle.actual_qty ELSE 0 END) AS outgoing_qty,
	 SUM(CASE WHEN sle.posting_date >= %(from_date)s THEN sle.stock_value_difference ELSE 0 END) AS value_change,
	 SUM(sle.actual_qty) AS balance_qty,SUM(sle.stock_value_difference) AS balance_value
	 FROM `tabStock Ledger Entry` sle JOIN `tabItem` i ON i.name=sle.item_code
	 WHERE {where} AND sle.posting_date <= %(to_date)s
	 GROUP BY sle.item_code,sle.warehouse ORDER BY sle.item_code,sle.warehouse""",
		values,
	)
	return [dict(r, currency=ctx.currency) for r in rows]


def inventory(ctx):
	rows = movement(ctx)
	by_key = {(r["item"], r["warehouse"]): r for r in rows}
	where, values = conditions(ctx)
	period = ctx.query(
		f"""SELECT sle.item_code AS item,sle.warehouse,sle.voucher_type,
	 se.purpose,se.stock_entry_type,SIGN(sle.actual_qty) AS direction,
	 SUM(sle.actual_qty) AS qty,SUM(sle.stock_value_difference) AS value,
	 EXISTS(SELECT 1 FROM `tabPOS Order` ord WHERE ord.recipe_stock_entry=se.name) AS recipe_issue
	 FROM `tabStock Ledger Entry` sle
	 LEFT JOIN `tabStock Entry` se ON se.name=sle.voucher_no AND sle.voucher_type='Stock Entry'
	 WHERE {where} AND sle.posting_date BETWEEN %(from_date)s AND %(to_date)s
	 GROUP BY sle.item_code,sle.warehouse,sle.voucher_type,se.purpose,se.stock_entry_type,direction,recipe_issue""",
		values,
	)
	fields = [
		"purchase",
		"purchase_return",
		"sales",
		"sales_return",
		"transfer_in",
		"transfer_out",
		"manufacture_in",
		"manufacture_out",
		"recipe_consumption",
		"waste",
		"reconciliation",
		"other_in",
		"other_out",
	]
	for r in rows:
		for f in fields:
			r[f + "_qty"] = 0
			r[f + "_value"] = 0
	for r in period:
		key = (r.item, r.warehouse)
		if key not in by_key:
			continue
		if r.voucher_type in {"Purchase Receipt", "Purchase Invoice"}:
			kind = "purchase" if r.qty > 0 else "purchase_return"
		elif r.voucher_type in {"Sales Invoice", "Delivery Note"}:
			kind = "sales_return" if r.qty > 0 else "sales"
		elif r.voucher_type == "Stock Reconciliation":
			kind = "reconciliation"
		elif r.purpose == "Material Transfer":
			kind = "transfer_in" if r.qty > 0 else "transfer_out"
		elif r.purpose == "Manufacture":
			kind = "manufacture_in" if r.qty > 0 else "manufacture_out"
		elif r.stock_entry_type == "Void":
			kind = "waste"
		elif r.recipe_issue:
			kind = "recipe_consumption"
		else:
			kind = "other_in" if r.qty > 0 else "other_out"
		by_key[key][kind + "_qty"] += flt(r.qty)
		by_key[key][kind + "_value"] += flt(r.value)
	if cint(ctx.filters.hide_zero):
		rows = [
			r
			for r in rows
			if any(
				abs(flt(r[k])) > 1e-8
				for k in ["opening_qty", "balance_qty", "incoming_qty", "outgoing_qty", "value_change"]
			)
		]
	cols = stock_columns() + [
		col("opening_qty", "Opening Quantity", "Float"),
		col("opening_value", "Opening Value"),
		col("incoming_qty", "Incoming Quantity", "Float"),
		col("outgoing_qty", "Outgoing Quantity", "Float"),
		col("balance_qty", "Closing Quantity", "Float"),
		col("balance_value", "Closing Value"),
		col("value_change", "Value Change"),
	]
	for key, label in [
		("purchase", "Purchases"),
		("purchase_return", "Purchase Returns"),
		("sales", "Sales Issues"),
		("sales_return", "Sales Returns"),
		("transfer_in", "Transfers In"),
		("transfer_out", "Transfers Out"),
		("manufacture_in", "Production In"),
		("manufacture_out", "Production Out"),
		("recipe_consumption", "Recipe Consumption"),
		("waste", "Waste"),
		("reconciliation", "Reconciliation"),
		("other_in", "Other Receipts"),
		("other_out", "Other Issues"),
	]:
		cols.extend([col(key + "_qty", label + " Quantity", "Float"), col(key + "_value", label + " Value")])
	return cols, rows


def stock_columns():
	return [
		col("item", "Item", "Link", "Item", 160),
		col("item_name", "Item Name", "Data", width=185),
		col("item_group", "Item Group", "Link", "Item Group"),
		col("warehouse", "Warehouse", "Link", "Warehouse", 170),
		col("uom", "Stock UOM", "Link", "UOM"),
	]


def valuation(ctx, diagnostics=False):
	where, values = conditions(ctx)
	rows = ctx.query(
		f"""SELECT q.*,q.previous_qty+q.actual_qty-q.qty_after_transaction AS quantity_variance,
	 q.previous_value+q.stock_value_difference-q.stock_value AS value_variance
	 FROM (
	 SELECT sle.name AS ledger_entry,sle.item_code AS item,i.item_name,i.item_group,i.stock_uom AS uom,
	 sle.warehouse,sle.posting_date,sle.posting_time,sle.voucher_type,sle.voucher_no,
	 sle.actual_qty,sle.qty_after_transaction,sle.stock_value,sle.stock_value_difference,
	 CASE WHEN sle.voucher_type='Stock Entry' THEN se.purpose ELSE sle.voucher_type END AS source_type,
	 sle.valuation_rate,sle.incoming_rate,sle.outgoing_rate,sle.recalculate_rate,
	 COALESCE(LAG(sle.qty_after_transaction) OVER w,0) AS previous_qty,
	 COALESCE(LAG(sle.stock_value) OVER w,0) AS previous_value,
	 LAG(sle.valuation_rate) OVER w AS previous_rate
	 FROM `tabStock Ledger Entry` sle JOIN `tabItem` i ON i.name=sle.item_code
	 LEFT JOIN `tabStock Entry` se ON sle.voucher_type='Stock Entry' AND se.name=sle.voucher_no
	 WHERE {where} AND sle.posting_date <= %(to_date)s
	 WINDOW w AS (PARTITION BY sle.item_code,sle.warehouse ORDER BY sle.posting_date,sle.posting_time,sle.creation,sle.name)
	 ) q WHERE q.posting_date >= %(from_date)s ORDER BY q.item,q.warehouse,q.posting_date,q.posting_time,q.ledger_entry""",
		values,
	)
	result = []
	for r in rows:
		r["currency"] = ctx.currency
		if diagnostics:
			reasons = []
			if r.recalculate_rate:
				reasons.append(_("Pending Rate Recalculation"))
			if abs(flt(r.quantity_variance)) > 0.000001:
				reasons.append(_("Quantity Balance Mismatch"))
			if abs(flt(r.value_variance)) > 0.02:
				reasons.append(_("Stock Value Mismatch"))
			if not reasons:
				continue
			r["issue"] = "; ".join(reasons)
		result.append(dict(r))
	cols = stock_columns() + [
		col("posting_date", "Posting Date", "Date"),
		col("posting_time", "Posting Time", "Time"),
		col("voucher_type", "Document Type", "Link", "DocType"),
		col("voucher_no", "Document", "Dynamic Link", "voucher_type", 190),
		col("source_type", "Movement Source", "Data", width=160),
		col("actual_qty", "Quantity Change", "Float"),
		col("previous_qty", "Previous Quantity", "Float"),
		col("qty_after_transaction", "Balance Quantity", "Float"),
		col("previous_rate", "Previous Valuation Rate"),
		col("valuation_rate", "Valuation Rate"),
		col("stock_value_difference", "Value Change"),
		col("stock_value", "Stock Value"),
	]
	if diagnostics:
		cols.extend(
			[
				col("issue", "Diagnostic", "Data", width=240),
				col("quantity_variance", "Quantity Variance", "Float"),
				col("value_variance", "Value Variance"),
			]
		)
	return cols, result


def draft_counts(ctx):
	warehouses = ctx.warehouse_scope()
	rows = ctx.query(
		"""SELECT sr.name AS stock_reconciliation,sr.posting_date,sr.posting_time,
	 d.item_code AS item,i.item_name,i.item_group,i.stock_uom AS uom,d.warehouse,
	 d.qty AS counted_qty,d.valuation_rate AS counted_rate,
	 COALESCE((SELECT SUM(sle.actual_qty) FROM `tabStock Ledger Entry` sle
	 WHERE sle.company=sr.company AND sle.item_code=d.item_code AND sle.warehouse=d.warehouse
	 AND sle.is_cancelled=0 AND TIMESTAMP(sle.posting_date,sle.posting_time)<=TIMESTAMP(sr.posting_date,sr.posting_time)),0) AS ledger_qty,
	 COALESCE((SELECT SUM(sle.stock_value_difference) FROM `tabStock Ledger Entry` sle
	 WHERE sle.company=sr.company AND sle.item_code=d.item_code AND sle.warehouse=d.warehouse
	 AND sle.is_cancelled=0 AND TIMESTAMP(sle.posting_date,sle.posting_time)<=TIMESTAMP(sr.posting_date,sr.posting_time)),0) AS ledger_value
	 FROM `tabStock Reconciliation` sr JOIN `tabStock Reconciliation Item` d ON d.parent=sr.name
	 JOIN `tabItem` i ON i.name=d.item_code WHERE sr.docstatus=0 AND sr.company=%(company)s
	 AND d.warehouse IN %(warehouses)s AND sr.posting_date BETWEEN %(from_date)s AND %(to_date)s
	 ORDER BY sr.posting_date,sr.name,d.idx""",
		{"warehouses": warehouses or [""]},
	)
	result = []
	for r in rows:
		if not matches_item(ctx, r):
			continue
		r["quantity_variance"] = flt(r.counted_qty) - flt(r.ledger_qty)
		r["value_variance"] = flt(r.counted_qty) * flt(r.counted_rate) - flt(r.ledger_value)
		r["currency"] = ctx.currency
		if abs(r["quantity_variance"]) < flt(ctx.filters.qty_threshold) or abs(r["value_variance"]) < flt(
			ctx.filters.value_threshold
		):
			continue
		result.append(dict(r))
	return [
		col("stock_reconciliation", "Stock Reconciliation", "Link", "Stock Reconciliation", 185)
	] + stock_columns() + [
		col("posting_date", "Posting Date", "Date"),
		col("counted_qty", "Counted Quantity", "Float"),
		col("ledger_qty", "Ledger Quantity", "Float"),
		col("quantity_variance", "Quantity Variance", "Float"),
		col("counted_rate", "Counted Rate"),
		col("ledger_value", "Ledger Value"),
		col("value_variance", "Value Variance"),
	], result


def requests(ctx, pending=False):
	rows = ctx.query("""SELECT mr.name AS request,mr.transaction_date,mr.schedule_date,mr.material_request_type,
	 mr.status,d.name AS request_item,d.item_code AS item,i.item_name,i.item_group,
	 d.uom,d.stock_uom,d.warehouse,d.qty,d.stock_qty,d.ordered_qty,d.received_qty,
	 COALESCE((SELECT SUM(sei.transfer_qty) FROM `tabStock Entry Detail` sei
	 JOIN `tabStock Entry` se ON se.name=sei.parent
	 WHERE sei.material_request_item=d.name AND se.docstatus=1 AND se.company=mr.company),0) AS actual_transferred
	 FROM `tabMaterial Request` mr JOIN `tabMaterial Request Item` d ON d.parent=mr.name
	 JOIN `tabItem` i ON i.name=d.item_code WHERE mr.company=%(company)s AND mr.docstatus=1
	 AND mr.status NOT IN ('Stopped','Cancelled') AND mr.transaction_date BETWEEN %(from_date)s AND %(to_date)s
	 ORDER BY mr.transaction_date,mr.name,d.idx""")
	warehouses = set(ctx.warehouse_scope())
	result = []
	for r in rows:
		if r.warehouse and r.warehouse not in warehouses:
			continue
		if ctx.filters.warehouse and not r.warehouse:
			continue
		if not matches_item(ctx, r):
			continue
		if pending:
			if r.material_request_type != "Purchase":
				continue
			r["remaining_qty"] = max(0, flt(r.qty) - flt(r.ordered_qty))
			if r["remaining_qty"] <= 0:
				continue
		else:
			if r.material_request_type != "Material Transfer":
				continue
			r["requested_qty"] = flt(r.stock_qty)
			r["transferred_qty"] = flt(r.actual_transferred)
			r["variance"] = r["requested_qty"] - r["transferred_qty"]
		result.append(dict(r, currency=ctx.currency))
	cols = [
		col("request", "Material Request", "Link", "Material Request", 180),
		col("transaction_date", "Request Date", "Date"),
		col("schedule_date", "Required Date", "Date"),
		col("status", "Status", "Data"),
		col("item", "Item", "Link", "Item"),
		col("item_name", "Item Name", "Data", width=180),
		col("warehouse", "Warehouse", "Link", "Warehouse"),
	]
	if pending:
		cols.extend(
			[
				col("uom", "UOM", "Link", "UOM"),
				col("qty", "Requested Quantity", "Float"),
				col("ordered_qty", "Ordered Quantity", "Float"),
				col("remaining_qty", "Pending Quantity", "Float"),
			]
		)
	else:
		cols.extend(
			[
				col("stock_uom", "Stock UOM", "Link", "UOM"),
				col("requested_qty", "Requested Quantity", "Float"),
				col("transferred_qty", "Transferred Quantity", "Float"),
				col("variance", "Unfulfilled Quantity", "Float"),
			]
		)
	return cols, result


def purchase_facts(ctx):
	# Receipts and direct invoices are disjoint; invoicing a receipt does not count
	# the same purchased stock a second time.
	rows = ctx.query("""SELECT 'Purchase Receipt' AS voucher_type,pr.name AS voucher_no,pr.posting_date,
	 pr.supplier,d.item_code AS item,i.item_name,i.item_group,i.stock_uom AS uom,
	 d.warehouse,d.stock_qty,d.base_net_amount AS value
	 FROM `tabPurchase Receipt` pr JOIN `tabPurchase Receipt Item` d ON d.parent=pr.name
	 JOIN `tabItem` i ON i.name=d.item_code WHERE pr.company=%(company)s AND pr.docstatus=1
	 AND pr.is_return=0 AND pr.posting_date BETWEEN %(from_date)s AND %(to_date)s
	 UNION ALL
	 SELECT 'Purchase Invoice',pi.name,pi.posting_date,pi.supplier,d.item_code,i.item_name,
	 i.item_group,i.stock_uom,d.warehouse,d.stock_qty,d.base_net_amount
	 FROM `tabPurchase Invoice` pi JOIN `tabPurchase Invoice Item` d ON d.parent=pi.name
	 JOIN `tabItem` i ON i.name=d.item_code WHERE pi.company=%(company)s AND pi.docstatus=1
	 AND pi.is_return=0 AND COALESCE(d.pr_detail,'')=''
	 AND pi.posting_date BETWEEN %(from_date)s AND %(to_date)s""")
	warehouses = set(ctx.warehouse_scope())
	return [
		dict(r)
		for r in rows
		if (not r.warehouse or r.warehouse in warehouses)
		and (not ctx.filters.warehouse or bool(r.warehouse))
		and matches_item(ctx, r)
		and (not ctx.filters.supplier or r.supplier == ctx.filters.supplier)
	]


def price_changes(current, previous, currency):
	def grouped(rows):
		result = {}
		for r in rows:
			if flt(r.get("stock_qty")) <= 0:
				continue
			g = result.setdefault(
				r["item"],
				dict(
					item=r["item"],
					item_name=r.get("item_name"),
					item_group=r.get("item_group"),
					uom=r.get("uom"),
					quantity=0,
					value=0,
					min_rate=None,
					max_rate=None,
				),
			)
			rate = flt(r["value"]) / flt(r["stock_qty"])
			g["quantity"] += flt(r["stock_qty"])
			g["value"] += flt(r["value"])
			g["min_rate"] = rate if g["min_rate"] is None else min(g["min_rate"], rate)
			g["max_rate"] = rate if g["max_rate"] is None else max(g["max_rate"], rate)
		for r in result.values():
			r["average_rate"] = r["value"] / r["quantity"] if r["quantity"] else None
		return result

	old = grouped(previous)
	now = grouped(current)
	for k, r in now.items():
		r["previous_rate"] = old.get(k, {}).get("average_rate")
		r["rate_change"] = r["average_rate"] - r["previous_rate"] if r["previous_rate"] is not None else None
		r["change_percent"] = (
			r["rate_change"] / r["previous_rate"] * 100
			if r["previous_rate"] and r["rate_change"] is not None
			else None
		)
		r["currency"] = currency
	return list(now.values())


def purchase_columns():
	return [
		col("item", "Item", "Link", "Item", 165),
		col("item_name", "Item Name", "Data", width=190),
		col("item_group", "Item Group", "Link", "Item Group"),
		col("uom", "Stock UOM", "Link", "UOM"),
		col("quantity", "Purchased Quantity", "Float"),
		col("value", "Purchase Value"),
		col("min_rate", "Minimum Unit Price"),
		col("max_rate", "Maximum Unit Price"),
		col("average_rate", "Weighted Average Price"),
		col("previous_rate", "Previous Period Price"),
		col("rate_change", "Unit Price Change"),
		col("change_percent", "Price Change %", "Percent"),
	]
