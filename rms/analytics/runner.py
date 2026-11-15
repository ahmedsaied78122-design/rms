"""One execution path for native reports, charts, cards and the report explorer."""

import frappe
from frappe import _

from rms.analytics.catalog import REPORTS, INVENTORY_FAMILIES, STATIC_FAMILIES, ENTERPRISE_FAMILIES
from rms.analytics.context import Context
from rms.analytics import sales
from rms.analytics.sales import col


def execute(key, filters=None, _previous=False):
	if key not in REPORTS:
		frappe.throw(_("Unknown RMS report."))
	spec = REPORTS[key]
	ctx = Context(spec, filters)
	if ctx.compare and ctx.group in {"week", "month"}:
		frappe.throw(_("Choose daily grouping to compare equal date periods."))
	if ctx.compare and ctx.filters.business_period:
		frappe.throw(_("Choose Selected Dates before comparing periods."))
	family = spec["family"]
	message = None
	summary = []
	chart = None
	if family in ENTERPRISE_FAMILIES:
		from rms.analytics import enterprise

		if family in {"erp_customers", "customer_cohorts"}:
			columns, data = enterprise.customers(ctx, family == "customer_cohorts")
			chart = sales.chart(
				data,
				"total",
				"Invoice Revenue Including Tax",
				"line" if family == "customer_cohorts" else "bar",
			)
		elif family in {"purchase_lines", "purchase_summary", "asset_purchases"}:
			columns, data = enterprise.purchases(
				ctx, family == "purchase_summary", family == "asset_purchases"
			)
			if family == "purchase_summary":
				chart = sales.chart([{**r, "label": r["item"]} for r in data], "value", "Net Purchase Value")
		elif family == "trade_flow":
			columns, data = enterprise.trade_flow(ctx)
			message = _(
				"Sales less purchases is a period flow comparison, not gross profit. Stock purchased in another period is not treated as current cost of sales."
			)
		elif family == "ledger_details":
			columns, data = enterprise.ledger(ctx)
		elif family in {"stock_sales", "material_issues"}:
			columns, data = enterprise.stock_issues(ctx, family == "stock_sales")
		elif family == "production":
			view = ctx.filters.production_view or "work_orders"
			if view not in {"work_orders", "job_cards", "quality"}:
				frappe.throw(_("Choose a supported production view."))
			columns, data = (
				enterprise.production(ctx)
				if view == "work_orders"
				else enterprise.production_jobs(ctx)
				if view == "job_cards"
				else enterprise.production_quality(ctx)
			)
			if view == "quality":
				statuses = {}
				for row in data:
					statuses[row["status"]] = statuses.get(row["status"], 0) + 1
				chart = sales.chart(
					[{"label": _(label), "count": count} for label, count in statuses.items()],
					"count",
					"Inspections",
				)
				message = _(
					"Submitted manufacturing inspections by inspection date. The sample size is not a count of rejected production units."
				)
			else:
				chart = sales.chart(
					[
						{**r, "label": r["work_order"] if view == "work_orders" else r["job_card"]}
						for r in data
					],
					"produced_qty" if view == "work_orders" else "actual_minutes",
					"Produced Quantity" if view == "work_orders" else "Recorded Minutes",
				)
				message = (
					_(
						"Production uses submitted Work Orders by planned start date. Unfinished orders have no on-time completion result."
					)
					if view == "work_orders"
					else _(
						"Job Cards use their posting date. Recorded minutes exclude running time that has not yet been saved in a time log."
					)
				)
			summary = [
				dict(
					label=_(
						"Work Orders"
						if view == "work_orders"
						else "Job Cards"
						if view == "job_cards"
						else "Inspections"
					),
					value=len(data),
					datatype="Int",
					indicator="Green",
				)
			]

		else:
			for doctype in (
				"Stock Ledger Entry",
				"Stock Entry" if family == "overhead_manufacturing" else "Sales Invoice",
			):
				if not frappe.has_permission(doctype, "report"):
					frappe.throw(_("You do not have permission to view this report."), frappe.PermissionError)
			columns, data = enterprise.overhead(ctx, family == "overhead_manufacturing")
			message = _(
				"Analysis only: the selected overhead account balance is allocated by positive stock-unit quantity across the filtered items. It does not post expenses or change stock valuations. Direct costs without stock movements remain blank."
			)
	elif family in INVENTORY_FAMILIES:
		columns, data = inventory_result(ctx, family)
	elif family in STATIC_FAMILIES:
		from rms.analytics.recipes import plan, recipe_columns

		if family == "ingredients" and not ctx.filters.item:
			frappe.throw(_("Choose an Ingredient to trace its recipes."))
		if family == "scenarios" and not ctx.filters.product:
			frappe.throw(_("Choose a Selling Product to inspect modifier scenarios."))
		recipe_family = "ingredients" if family == "recipe_compare" else family
		columns = recipe_columns(recipe_family)
		data = plan(ctx, recipe_family)
		message = _(
			"Planning uses the current recipe and Item valuation. Choose a Store and Order Type to include their price rules and packaging."
		)
		chart = (
			sales.chart(
				[{**r, "label": r.get("title") or r["product"]} for r in data],
				"gross_profit",
				"Planned Gross Profit",
			)
			if family == "planned_margin"
			else None
		)
	elif family == "dormant":
		from rms.analytics.derived import dormant

		columns, data = dormant(ctx)
	elif family in {"notes", "cancellations", "returns", "kitchen", "printing", "occupancy"}:
		from rms.analytics import operations

		columns, data = getattr(operations, family)(ctx)
		if family == "kitchen":
			message = _(
				"Delay uses the optional analysis target entered above. Blank means no target; historical product preparation targets are not stored in RMS."
			)
			chart = sales.chart(
				[{**r, "label": r["preparation_area"]} for r in data],
				"prep_minutes",
				"Average Preparation Minutes",
			)
		if family == "printing":
			chart = sales.chart(
				[{**r, "label": r["print_device"]} for r in data], "printed", "Printed Receipts"
			)
		if family == "occupancy":
			message = _(
				"Overlapping checks count as one occupied period. Closures without a saved event timestamp are counted separately. Working-hours filtering uses the current configured schedule."
			)
	else:
		facts = sales.invoice_facts(ctx)
		if family == "payments":
			data = sales.payment_rows(ctx, facts)
			columns = [
				col("label", "Mode of Payment", "Link", "Mode of Payment", 190),
				col("invoice_count", "Invoices", "Int"),
				col("amount", "Net Tender Amount"),
				col("contribution", "Contribution %", "Percent"),
			]
			chart = sales.chart(data, "amount", "Net Tender Amount", "donut")
		elif family == "customers":
			data = sales.aggregate(facts, "customer", ctx.currency)
			columns = sales.columns("customer")
			visits = {}
			for r in facts:
				if not r.get("is_return"):
					visits.setdefault(r["customer"], set()).add(str(r["business_date"]))
			for r in data:
				r["visits"] = len(visits.get(r["group_key"], set()))
				r["net_value"] = r["revenue"]
			columns.append(col("visits", "Visit Days", "Int"))
			chart = sales.chart(data)
		elif family == "business_day":
			from rms.analytics.derived import daily_operations

			columns, data = daily_operations(ctx, facts)
			message = _(
				"Sales follow POS scope. Posted expenses require expense report permission and remain Store-level; they are not allocated by Brand or Order Type."
			)
		elif family == "consumption":
			from rms.analytics.derived import consumption

			columns, data = consumption(ctx, facts)
			message = _(
				"Consumption is attributed from saved recipe quantities and posted stock movements. Unvalued movements are excluded; waste is included only when selected."
			)
		elif family == "price_impact":
			from rms.analytics.derived import price_impact

			columns, data = price_impact(facts, ctx.currency)
			chart = sales.chart(data, "price_impact", "Price Impact")
		elif family in {"margin", "margin_change", "engineering"}:
			from rms.analytics.costs import attach_actual_costs, margin_rows, engineer

			attach_actual_costs(ctx, facts)
			data = margin_rows(facts, ctx.group, ctx.currency)
			columns = sales.columns(ctx.group) + [
				col("cost", "Posted Cost"),
				col("gross_profit", "Gross Profit"),
				col("margin_percent", "Gross Margin %", "Percent"),
				col("unvalued_lines", "Unvalued Lines", "Int"),
			]
			if family == "engineering":
				data = engineer(data)
				columns.extend(
					[
						col("sales_mix", "Sales Mix %", "Percent"),
						col("classification", "Portfolio Position", "Data", width=170),
					]
				)
			chart = sales.chart(data, "gross_profit", "Gross Profit")
			missing = sum(r["unvalued_lines"] for r in data)
			message = _(
				"Actual margin uses posted stock valuations. Pending consolidation or missing historical movement allocations remain blank."
			)
			valued = [r for r in data if r.get("gross_profit") is not None]
			summary = [
				dict(
					label=_(label),
					value=value,
					datatype=kind,
					currency=ctx.currency,
					indicator="Orange" if missing else "Green",
				)
				for label, value, kind in [
					("Valued Net Revenue", sum(r["revenue"] for r in valued), "Currency"),
					("Posted Cost", sum(r["cost"] for r in valued), "Currency"),
					("Valued Gross Profit", sum(r["gross_profit"] for r in valued), "Currency"),
					("Unvalued Lines", missing, "Int"),
				]
			]
			if family == "margin_change" and not _previous:
				ctx.compare = True
		else:
			if family == "discounts":
				facts = [r for r in facts if abs(r["allocated_discount"]) > 0.000001]
			data = sales.aggregate(facts, ctx.group, ctx.currency)
			columns = sales.columns(ctx.group)
			if family == "rounding":
				data = [r for r in data if abs(r["rounding"]) > 0.000001]
				chart = sales.chart(data, "rounding", "Rounding Difference")
			else:
				chart = sales.chart(
					data, kind="line" if ctx.group in {"date", "hour", "week", "month"} else "bar"
				)
		if not summary:
			summary = sales.summary(facts, ctx.currency)
		if ctx.compare and family not in {"payments", "consumption", "business_day"}:
			previous_filters = ctx.previous_filters()
			previous = execute(key, previous_filters, _previous=True)
			# Comparison execution cannot recurse; Margin Movement uses an explicit internal flag.
			data, extra = compare_rows(
				data, previous[1], family, ctx.group, (ctx.to_date - ctx.from_date).days + 1
			)
			columns.extend(extra)
	for r in data:
		r.setdefault("currency", ctx.currency)
		for field in ("status", "source_type"):
			if r.get(field):
				r[field] = _(r[field])
	return columns, data, message, chart, summary


def compare_rows(current, previous, family, group=None, period_days=0):
	measure = "gross_profit" if family in {"margin", "margin_change", "engineering"} else "revenue"
	old = {}
	for r in previous:
		key = r.get("group_key", r.get("label"))
		if group == "date":
			from frappe.utils import add_days

			key = str(add_days(key, period_days))
		old[str(key)] = r
	result = []
	keys = {str(r.get("group_key", r.get("label"))) for r in current}
	merged = list(current)
	for key, prior in old.items():
		if key not in keys:
			row = {
				**prior,
				**{field: 0 for field in sales.MEASURES},
				"invoice_count": 0,
				"return_count": 0,
				"cost": 0,
				"gross_profit": 0,
				"unvalued_lines": 0,
				"average_invoice": 0,
				"discount_percent": 0,
				"contribution": 0,
				"margin_percent": None,
				"unit_profit": None,
				"sales_mix": 0,
				"classification": None,
				"group_key": key,
			}
			if group == "date":
				row["label"] = key
			merged.append(row)
	for r in merged:
		row = dict(r)
		prior = old.get(str(r.get("group_key", r.get("label"))))
		row["previous_value"] = prior.get(measure) if prior else None
		value = row.get(measure)
		row["value_change"] = (
			value - row["previous_value"] if value is not None and row["previous_value"] is not None else None
		)
		row["change_percent"] = (
			row["value_change"] / abs(row["previous_value"]) * 100
			if row["previous_value"] and row["value_change"] is not None
			else None
		)
		result.append(row)
	return result, [
		col("previous_value", "Previous Period"),
		col("value_change", "Period Change"),
		col("change_percent", "Period Change %", "Percent"),
	]


def inventory_result(ctx, family):
	from rms.analytics import inventory

	if family == "availability":
		from rms.analytics.derived import availability

		return availability(ctx)
	if family == "inventory":
		return inventory.inventory(ctx)
	if family == "draft_counts":
		return inventory.draft_counts(ctx)
	if family == "reposts":
		return inventory.valuation(ctx, True)
	if family == "valuation":
		return inventory.valuation(ctx)
	if family == "fulfillment":
		return inventory.requests(ctx)
	if family == "purchase_requests":
		return inventory.requests(ctx, True)
	if family == "purchase_prices":
		previous = Context(ctx.spec, ctx.previous_filters())
		rows = inventory.price_changes(
			inventory.purchase_facts(ctx), inventory.purchase_facts(previous), ctx.currency
		)
		return inventory.purchase_columns(), rows
	frappe.throw(_("Unsupported inventory report."))
