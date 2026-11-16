"""Enterprise views using native ERP ledgers; no duplicated financial postings."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from rms.analytics.context import limited, names
from rms.analytics.inventory import matches_item
from rms.analytics.sales import col


def customer_facts(ctx):
	rows = ctx.query("""SELECT si.name AS sales_invoice,si.posting_date,si.customer,si.customer_name,
	 si.customer_group,si.is_return,si.total_qty,si.base_net_total,si.base_grand_total,
	 (SELECT MIN(first.posting_date) FROM `tabSales Invoice` first WHERE first.customer=si.customer
	 AND first.company=si.company AND first.docstatus=1 AND first.is_return=0) AS first_purchase
	 FROM `tabSales Invoice` si WHERE si.company=%(company)s AND si.docstatus=1
	 AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s ORDER BY si.posting_date,si.name""")
	return [r for r in rows if not ctx.filters.customer or r.customer == ctx.filters.customer]


def customers(ctx, cohorts=False):
	groups = {}
	for r in customer_facts(ctx):
		period = str(r.posting_date)[:7]
		key = period if cohorts else r.customer
		g = groups.setdefault(
			key,
			dict(
				label=key,
				customer=r.customer,
				customer_name=r.customer_name,
				customer_group=r.customer_group,
				first_purchase=r.first_purchase,
				last_purchase=r.posting_date,
				invoice_count=0,
				return_count=0,
				quantity=0,
				revenue=0,
				total=0,
				new_revenue=0,
				repeat_revenue=0,
				_new=set(),
				_repeat=set(),
				currency=ctx.currency,
			),
		)
		g["invoice_count"] += int(not r.is_return)
		g["return_count"] += int(bool(r.is_return))
		g["quantity"] += flt(r.total_qty)
		g["revenue"] += flt(r.base_net_total)
		g["total"] += flt(r.base_grand_total)
		g["last_purchase"] = max(g["last_purchase"], r.posting_date)
		kind = "new" if str(r.first_purchase)[:7] == period else "repeat"
		g[kind + "_revenue"] += flt(r.base_grand_total)
		g["_" + kind].add(r.customer)
	data = []
	for g in groups.values():
		g["average_invoice"] = (
			g["total"] / (g["invoice_count"] + g["return_count"])
			if g["invoice_count"] + g["return_count"]
			else None
		)
		for kind in ("new", "repeat"):
			g[kind + "_customers"] = len(g["_" + kind])
			g[kind + "_average"] = g[kind + "_revenue"] / len(g["_" + kind]) if g["_" + kind] else None
		g["customer_average"] = (
			g["total"] / len(g["_new"] | g["_repeat"]) if g["_new"] | g["_repeat"] else None
		)
		g.pop("_new")
		g.pop("_repeat")
		data.append(g)
	if cohorts:
		columns = [
			col("label", "Month", "Data"),
			col("new_customers", "New Customers", "Int"),
			col("repeat_customers", "Repeat Customers", "Int"),
			col("new_revenue", "New Customer Revenue"),
			col("repeat_revenue", "Repeat Customer Revenue"),
			col("total", "Invoice Revenue Including Tax"),
			col("new_average", "Average New Customer Revenue"),
			col("repeat_average", "Average Repeat Customer Revenue"),
			col("customer_average", "Average Revenue per Customer"),
		]
	else:
		columns = [
			col("customer", "Customer", "Link", "Customer", 180),
			col("customer_name", "Customer Name", "Data", width=180),
			col("customer_group", "Customer Group", "Link", "Customer Group"),
			col("first_purchase", "First Purchase", "Date"),
			col("last_purchase", "Last Purchase", "Date"),
			col("invoice_count", "Invoices", "Int"),
			col("return_count", "Credit Notes", "Int"),
			col("quantity", "Net Quantity", "Float"),
			col("revenue", "Net Revenue"),
			col("total", "Invoice Revenue Including Tax"),
			col("average_invoice", "Average Document Value"),
		]
	return columns, sorted(data, key=lambda r: r["label"])


def purchases(ctx, summary=False, assets=False):
	rows = ctx.query("""SELECT pi.name AS purchase_invoice,pi.posting_date,pi.supplier,pi.is_return,
	 d.item_code AS item,d.item_name,i.item_group,d.stock_uom AS uom,d.stock_qty AS quantity,
	 d.base_net_amount AS value,d.warehouse,d.expense_account AS account,d.cost_center,
	 d.is_fixed_asset,d.asset_category,d.purchase_receipt
	 FROM `tabPurchase Invoice` pi JOIN `tabPurchase Invoice Item` d ON d.parent=pi.name
	 LEFT JOIN `tabItem` i ON i.name=d.item_code WHERE pi.docstatus=1 AND pi.company=%(company)s
	 AND pi.posting_date BETWEEN %(from_date)s AND %(to_date)s ORDER BY pi.posting_date,pi.name,d.idx""")
	warehouses = set(ctx.warehouse_scope())
	data = [
		dict(r, currency=ctx.currency)
		for r in rows
		if matches_item(ctx, r)
		and (not ctx.filters.supplier or r.supplier == ctx.filters.supplier)
		and (not assets or r.is_fixed_asset)
		and (not r.warehouse or r.warehouse in warehouses)
		and (not ctx.filters.warehouse or r.warehouse in warehouses)
	]
	if summary:
		groups = {}
		for r in data:
			key = (r["supplier"], r["item"], r["uom"])
			g = groups.setdefault(key, {**r, "quantity": 0, "value": 0, "_invoices": set()})
			g["quantity"] += flt(r["quantity"])
			g["value"] += flt(r["value"])
			g["_invoices"].add(r["purchase_invoice"])
		data = list(groups.values())
		for r in data:
			r["invoice_count"] = len(r.pop("_invoices"))
	for r in data:
		r["unit_price"] = r["value"] / r["quantity"] if r["quantity"] else None
	columns = [
		col("supplier", "Supplier", "Link", "Supplier", 170),
		col("item", "Item", "Link", "Item", 160),
		col("item_name", "Item Name", "Data", width=200),
		col("uom", "Stock UOM", "Link", "UOM"),
		col("quantity", "Net Purchased Quantity", "Float"),
		col("value", "Net Purchase Value"),
		col("unit_price", "Weighted Average Price"),
	]
	if summary:
		columns.append(col("invoice_count", "Invoices", "Int"))
	else:
		columns = [
			col("purchase_invoice", "Purchase Invoice", "Link", "Purchase Invoice", 190),
			col("posting_date", "Posting Date", "Date"),
		] + columns
		columns.extend(
			[
				col("warehouse", "Warehouse", "Link", "Warehouse"),
				col("account", "Expense Account", "Link", "Account"),
				col("cost_center", "Cost Center", "Link", "Cost Center"),
				col("is_fixed_asset", "Fixed Asset", "Check"),
				col("asset_category", "Asset Category", "Link", "Asset Category"),
			]
		)
	return columns, data


def ledger(ctx):
	# Delegate all balance/opening/closing/accounting-dimension calculations to
	# the installed native General Ledger, then annotate each voucher once per GL row.
	from erpnext.accounts.report.general_ledger.general_ledger import execute

	filters = frappe._dict(
		company=ctx.company,
		from_date=str(ctx.from_date),
		to_date=str(ctx.to_date),
		categorize_by="Categorize by Voucher (Consolidated)",
		show_remarks=1,
	)
	for key in ("account", "cost_center"):
		selected = names(ctx.filters.get(key))
		for name in selected:
			dt = "Account" if key == "account" else "Cost Center"
			if frappe.get_cached_value(dt, name, "company") != ctx.company or not frappe.has_permission(
				dt, doc=name
			):
				frappe.throw(
					_("Choose an accessible Account or Cost Center in this Company."), frappe.PermissionError
				)
		if selected:
			filters[key] = selected
	if ctx.filters.party_type:
		if ctx.filters.party_type not in {"Customer", "Supplier"}:
			frappe.throw(_("Choose Customer or Supplier as the party type."))
		filters.party_type = ctx.filters.party_type
		if ctx.filters.party:
			if not frappe.has_permission(ctx.filters.party_type, doc=ctx.filters.party):
				frappe.throw(_("This party is not available to you."), frappe.PermissionError)
			filters.party = [ctx.filters.party]
	columns, rows = execute(filters)
	rows = limited(rows)
	# Native report permission rules apply to the full financial rows before
	# looking up voucher children. Annotation never multiplies ledger amounts.
	from frappe.desk.query_report import get_filtered_data

	rows = get_filtered_data("GL Entry", columns, rows, ctx.user)
	items = defaultdict(list)
	for dt in ("Sales Invoice", "Purchase Invoice", "Stock Entry"):
		vouchers = list(
			{r.get("voucher_no") for r in rows if r.get("voucher_type") == dt and r.get("voucher_no")}
		)
		if not vouchers or not frappe.has_permission(dt, "read"):
			continue
		visible = frappe.get_list(
			dt, filters={"name": ["in", vouchers], "company": ctx.company}, pluck="name", limit_page_length=0
		)
		if not visible:
			continue
		child = "Stock Entry Detail" if dt == "Stock Entry" else dt + " Item"
		for r in ctx.query(
			f"SELECT parent,item_code,item_name,qty,uom FROM `tab{child}` WHERE parent IN %(vouchers)s ORDER BY parent,idx",
			{"vouchers": visible},
		):
			items[(dt, r.parent)].append(
				f"{r.item_code} · {r.item_name or ''} · {flt(r.qty):g} {r.uom or ''}"
			)
	for r in rows:
		r["item_details"] = " | ".join(items.get((r.get("voucher_type"), r.get("voucher_no")), []))
	columns.append(col("item_details", "Voucher Item Details", "Data", width=420))
	return columns, rows


def trade_flow(ctx):
	if not frappe.has_permission("Purchase Invoice", "report"):
		frappe.throw(_("You do not have permission to view this report."), frappe.PermissionError)
	groups = {}
	warehouses = set(ctx.warehouse_scope())
	for dt, kind, alias in (
		("Sales Invoice", "sales", "sales_invoice"),
		("Purchase Invoice", "purchases", "purchase_invoice"),
	):
		rows = ctx.query(f"""SELECT doc.name AS {alias},doc.posting_date,d.item_code AS item,i.item_name,i.item_group,
		 i.stock_uom AS uom,d.warehouse,d.stock_qty,d.base_net_amount FROM `tab{dt}` doc
		 JOIN `tab{dt} Item` d ON d.parent=doc.name JOIN `tabItem` i ON i.name=d.item_code
		 WHERE doc.company=%(company)s AND doc.docstatus=1 AND doc.posting_date BETWEEN %(from_date)s AND %(to_date)s""")
		for r in rows:
			if (
				not matches_item(ctx, r)
				or (r.warehouse and r.warehouse not in warehouses)
				or (ctx.filters.warehouse and not r.warehouse)
			):
				continue
			key = (str(r.posting_date)[:7], r.item)
			g = groups.setdefault(
				key,
				dict(
					month=key[0],
					item=r.item,
					item_name=r.item_name,
					uom=r.uom,
					sales_qty=0,
					sales_value=0,
					purchases_qty=0,
					purchases_value=0,
					currency=ctx.currency,
				),
			)
			g[kind + "_qty"] += flt(r.stock_qty)
			g[kind + "_value"] += flt(r.base_net_amount)
	for r in groups.values():
		r["flow_difference"] = r["sales_value"] - r["purchases_value"]
	return [
		col("month", "Month", "Data"),
		col("item", "Item", "Link", "Item"),
		col("item_name", "Item Name", "Data", width=190),
		col("uom", "Stock UOM", "Link", "UOM"),
		col("sales_qty", "Net Sold Quantity", "Float"),
		col("sales_value", "Net Sales Value"),
		col("purchases_qty", "Net Purchased Quantity", "Float"),
		col("purchases_value", "Net Purchase Value"),
		col("flow_difference", "Sales Less Purchases"),
	], sorted(groups.values(), key=lambda r: (r["month"], r["item"]))


def stock_issues(ctx, sales_only=False):
	from rms.analytics.inventory import conditions, stock_columns

	where, values = conditions(ctx)
	predicate = (
		"sle.voucher_type='Sales Invoice'" if sales_only else "se.purpose='Material Issue' AND se.docstatus=1"
	)
	rows = ctx.query(
		f"""SELECT sle.item_code AS item,i.item_name,i.item_group,sle.stock_uom AS uom,sle.warehouse,
	 -SUM(sle.actual_qty) AS quantity,-SUM(sle.stock_value_difference) AS value
	 FROM `tabStock Ledger Entry` sle JOIN `tabItem` i ON i.name=sle.item_code
	 LEFT JOIN `tabStock Entry` se ON sle.voucher_type='Stock Entry' AND sle.voucher_no=se.name
	 WHERE {where} AND sle.posting_date BETWEEN %(from_date)s AND %(to_date)s AND sle.actual_qty<0
	 AND {predicate}
	 GROUP BY sle.item_code,sle.warehouse,i.stock_uom""",
		values,
	)
	return stock_columns() + [
		col("quantity", "Issued Quantity", "Float"),
		col("value", "Posted Issue Value"),
	], [dict(r, currency=ctx.currency) for r in rows]


def production(ctx):
	rows = ctx.query("""SELECT w.name AS work_order,w.production_item AS item,i.item_name,i.item_group,
	 i.stock_uom AS uom,w.status,w.qty AS planned_qty,w.produced_qty,w.process_loss_qty,
	 w.planned_start_date,w.planned_end_date,w.actual_start_date,w.actual_end_date,
	 w.actual_operating_cost,w.planned_operating_cost,w.fg_warehouse AS warehouse,w.bom_no
	 FROM `tabWork Order` w JOIN `tabItem` i ON i.name=w.production_item
	 WHERE w.company=%(company)s AND w.docstatus=1 AND DATE(COALESCE(w.planned_start_date,w.creation))
	 BETWEEN %(from_date)s AND %(to_date)s ORDER BY w.planned_start_date,w.name""")
	warehouses = set(ctx.warehouse_scope())
	data = []
	for r in rows:
		if (
			not matches_item(ctx, r)
			or (r.warehouse and r.warehouse not in warehouses)
			or (ctx.filters.warehouse and not r.warehouse)
		):
			continue
		r["remaining_qty"] = max(0, flt(r.planned_qty) - flt(r.produced_qty) - flt(r.process_loss_qty))
		r["completion_percent"] = flt(r.produced_qty) / flt(r.planned_qty) * 100 if r.planned_qty else None
		r["loss_percent"] = flt(r.process_loss_qty) / flt(r.planned_qty) * 100 if r.planned_qty else None
		r["operating_variance"] = flt(r.actual_operating_cost) - flt(r.planned_operating_cost)
		r["on_time"] = (
			int(r.actual_end_date <= r.planned_end_date) if r.actual_end_date and r.planned_end_date else None
		)
		data.append(dict(r, currency=ctx.currency))
	return [
		col("work_order", "Work Order", "Link", "Work Order", 190),
		col("item", "Item", "Link", "Item"),
		col("item_name", "Item Name", "Data", width=190),
		col("status", "Status", "Data"),
		col("warehouse", "Warehouse", "Link", "Warehouse"),
		col("uom", "Stock UOM", "Link", "UOM"),
		col("planned_qty", "Planned Quantity", "Float"),
		col("produced_qty", "Produced Quantity", "Float"),
		col("remaining_qty", "Remaining Quantity", "Float"),
		col("process_loss_qty", "Process Loss Quantity", "Float"),
		col("completion_percent", "Production Completion %", "Percent"),
		col("loss_percent", "Process Loss %", "Percent"),
		col("planned_end_date", "Planned Completion", "Datetime"),
		col("actual_end_date", "Actual Completion", "Datetime"),
		col("on_time", "Completed on Time", "Check"),
		col("planned_operating_cost", "Planned Operating Cost"),
		col("actual_operating_cost", "Actual Operating Cost"),
		col("operating_variance", "Operating Cost Variance"),
	], data


def production_jobs(ctx):
	if not frappe.has_permission("Job Card", "report"):
		frappe.throw(_("You do not have permission to view this report."), frappe.PermissionError)
	rows = ctx.query("""SELECT j.name AS job_card,j.work_order,j.posting_date,j.production_item AS item,i.item_name,i.item_group,
	 i.stock_uom AS uom,j.workstation,j.operation,j.status,j.for_quantity AS planned_qty,j.total_completed_qty AS produced_qty,
	 j.process_loss_qty,j.time_required AS planned_minutes,j.total_time_in_mins AS actual_minutes,
	 j.expected_start_date,j.expected_end_date,j.actual_start_date,j.actual_end_date,j.wip_warehouse AS warehouse
	 FROM `tabJob Card` j JOIN `tabItem` i ON i.name=j.production_item
	 WHERE j.company=%(company)s AND j.docstatus<2 AND j.posting_date BETWEEN %(from_date)s AND %(to_date)s
	 ORDER BY j.posting_date,j.name""")
	warehouses = set(ctx.warehouse_scope())
	data = []
	for r in rows:
		if (
			not matches_item(ctx, r)
			or (r.warehouse and r.warehouse not in warehouses)
			or (ctx.filters.warehouse and not r.warehouse)
		):
			continue
		r["time_variance"] = flt(r.actual_minutes) - flt(r.planned_minutes)
		r["completion_percent"] = flt(r.produced_qty) / flt(r.planned_qty) * 100 if r.planned_qty else None
		data.append(dict(r, currency=ctx.currency))
	return [
		col("job_card", "Job Card", "Link", "Job Card", 180),
		col("work_order", "Work Order", "Link", "Work Order", 180),
		col("posting_date", "Posting Date", "Date"),
		col("item", "Item", "Link", "Item"),
		col("item_name", "Item Name", "Data", width=190),
		col("workstation", "Workstation", "Link", "Workstation"),
		col("operation", "Operation", "Link", "Operation"),
		col("status", "Status", "Data"),
		col("uom", "Stock UOM", "Link", "UOM"),
		col("planned_qty", "Planned Quantity", "Float"),
		col("produced_qty", "Produced Quantity", "Float"),
		col("process_loss_qty", "Process Loss Quantity", "Float"),
		col("completion_percent", "Production Completion %", "Percent"),
		col("planned_minutes", "Planned Minutes", "Float"),
		col("actual_minutes", "Recorded Minutes", "Float"),
		col("time_variance", "Time Variance Minutes", "Float"),
		col("actual_start_date", "Actual Start", "Datetime"),
		col("actual_end_date", "Actual Completion", "Datetime"),
	], data


def production_quality(ctx):
	if not frappe.has_permission("Quality Inspection", "report"):
		frappe.throw(_("You do not have permission to view this report."), frappe.PermissionError)
	rows = ctx.query("""SELECT qi.name AS inspection,qi.report_date,qi.item_code AS item,i.item_name,i.item_group,
	 qi.reference_type,qi.reference_name,qi.status,qi.sample_size,qi.inspected_by,
	 qi.verified_by,j.work_order,COALESCE(j.wip_warehouse,se.from_warehouse,se.to_warehouse) AS warehouse
	 FROM `tabQuality Inspection` qi JOIN `tabItem` i ON i.name=qi.item_code
	 LEFT JOIN `tabJob Card` j ON qi.reference_type='Job Card' AND j.name=qi.reference_name
	 LEFT JOIN `tabStock Entry` se ON qi.reference_type='Stock Entry' AND se.name=qi.reference_name
	 WHERE qi.docstatus=1 AND COALESCE(NULLIF(qi.company,''),j.company,se.company)=%(company)s
	 AND (j.name IS NOT NULL OR se.purpose IN ('Manufacture','Repack'))
	 AND qi.report_date BETWEEN %(from_date)s AND %(to_date)s ORDER BY qi.report_date,qi.name""")
	warehouses = set(ctx.warehouse_scope())
	data = [
		dict(r, currency=ctx.currency)
		for r in rows
		if matches_item(ctx, r)
		and (not r.warehouse or r.warehouse in warehouses)
		and (not ctx.filters.warehouse or r.warehouse in warehouses)
	]
	return [
		col("inspection", "Quality Inspection", "Link", "Quality Inspection", 180),
		col("report_date", "Inspection Date", "Date"),
		col("item", "Item", "Link", "Item"),
		col("item_name", "Item Name", "Data", width=190),
		col("reference_type", "Reference Type", "Data"),
		col("reference_name", "Reference Document", "Dynamic Link", "reference_type", 190),
		col("work_order", "Work Order", "Link", "Work Order"),
		col("status", "Status", "Data"),
		col("sample_size", "Sample Size", "Float"),
		col("inspected_by", "Inspected By", "Link", "User"),
		col("verified_by", "Verified By", "Data"),
	], data


def overhead(ctx, manufacturing=False):
	# This is an explicit analysis scenario, never a posting or a valuation rewrite.
	# Require an overhead account so direct costs are not silently allocated twice.
	account, center = ctx.filters.account, ctx.filters.cost_center
	if not account or not center:
		frappe.throw(_("Choose an Overhead Expense Account and Cost Center for this allocation scenario."))
	for dt, name in (("Account", account), ("Cost Center", center)):
		if frappe.get_cached_value(dt, name, "company") != ctx.company or not frappe.has_permission(
			dt, doc=name
		):
			frappe.throw(
				_("Choose an accessible Account or Cost Center in this Company."), frappe.PermissionError
			)
	if frappe.get_cached_value("Account", account, "root_type") != "Expense":
		frappe.throw(_("Choose an Expense Account for overhead allocation."))
	bounds = frappe.db.get_value("Cost Center", center, ["lft", "rgt"], as_dict=True)
	centers = frappe.get_list(
		"Cost Center",
		filters={"company": ctx.company, "lft": [">=", bounds.lft], "rgt": ["<=", bounds.rgt]},
		pluck="name",
		limit_page_length=0,
	)
	account_bounds = frappe.db.get_value("Account", account, ["lft", "rgt"], as_dict=True)
	accounts = frappe.get_list(
		"Account",
		filters={
			"company": ctx.company,
			"root_type": "Expense",
			"lft": [">=", account_bounds.lft],
			"rgt": ["<=", account_bounds.rgt],
		},
		pluck="name",
		limit_page_length=0,
	)
	entries = ctx.query(
		"""SELECT account,cost_center,debit,credit FROM `tabGL Entry`
	 WHERE company=%(company)s AND is_cancelled=0 AND account IN %(accounts)s AND cost_center IN %(centers)s
	 AND voucher_type NOT IN ('Sales Invoice','Delivery Note') AND posting_date BETWEEN %(from_date)s AND %(to_date)s""",
		{"accounts": accounts or [""], "centers": centers or [""]},
	)
	amount = sum(flt(r.debit) - flt(r.credit) for r in entries)
	warehouses = set(ctx.warehouse_scope())
	if manufacturing:
		facts = ctx.query("""SELECT se.name AS stock_entry,d.item_code AS item,i.item_name,i.item_group,
		 i.stock_uom AS uom,d.t_warehouse AS warehouse,d.transfer_qty AS quantity,d.amount AS cost
		 FROM `tabStock Entry` se JOIN `tabStock Entry Detail` d ON d.parent=se.name JOIN `tabItem` i ON i.name=d.item_code
		 WHERE se.docstatus=1 AND se.company=%(company)s AND se.purpose IN ('Manufacture','Repack')
		 AND d.is_finished_item=1 AND se.posting_date BETWEEN %(from_date)s AND %(to_date)s""")
	else:
		facts = ctx.query("""SELECT si.name AS sales_invoice,d.item_code AS item,i.item_name,i.item_group,
		 i.stock_uom AS uom,d.warehouse,d.stock_qty AS quantity,
		 (SELECT -SUM(sle.stock_value_difference) FROM `tabStock Ledger Entry` sle
		 WHERE sle.voucher_type='Sales Invoice' AND sle.voucher_no=si.name AND sle.voucher_detail_no=d.name AND sle.is_cancelled=0) AS cost
		 FROM `tabSales Invoice` si JOIN `tabSales Invoice Item` d ON d.parent=si.name JOIN `tabItem` i ON i.name=d.item_code
		 WHERE si.docstatus=1 AND si.company=%(company)s AND si.is_return=0
		 AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s""")
	facts = [r for r in facts if matches_item(ctx, r) and r.warehouse in warehouses and flt(r.quantity) > 0]
	groups = {}
	for r in facts:
		g = groups.setdefault(
			(r.item, r.uom),
			dict(
				item=r.item,
				item_name=r.item_name,
				uom=r.uom,
				quantity=0,
				cost=0,
				_missing=False,
				currency=ctx.currency,
			),
		)
		g["quantity"] += flt(r.quantity)
		g["cost"] += flt(r.cost)
		g["_missing"] |= r.cost is None
	total_qty = sum(g["quantity"] for g in groups.values())
	for g in groups.values():
		g["allocated_overhead"] = amount * g["quantity"] / total_qty if total_qty else None
		if g.pop("_missing"):
			g["cost"] = None
		g["total_cost"] = g["cost"] + g["allocated_overhead"] if g["cost"] is not None else None
		g["unit_cost"] = (
			g["total_cost"] / g["quantity"] if g["total_cost"] is not None and g["quantity"] else None
		)
	return [
		col("item", "Item", "Link", "Item"),
		col("item_name", "Item Name", "Data", width=190),
		col("uom", "Stock UOM", "Link", "UOM"),
		col("quantity", "Allocation Quantity", "Float"),
		col("cost", "Posted Direct Cost"),
		col("allocated_overhead", "Allocated Overhead"),
		col("total_cost", "Scenario Total Cost"),
		col("unit_cost", "Scenario Unit Cost"),
	], list(groups.values())
