"""Derived views with explicit provenance and currency-safe aggregation."""

from collections import defaultdict
from copy import copy
import math

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, getdate

from rms.analytics.context import names
from rms.analytics.sales import col
from rms.analytics.recipes import Planning, catalog
from rms.snapshots import parse_json_rows


def dormant(ctx):
	days = cint(ctx.filters.dormant_days or 30)
	if days < 1:
		frappe.throw(_("Dormant days must be greater than zero."))
	last = ctx.query("""SELECT p.name AS product,MAX(pi.posting_date) AS last_sale
	 FROM `tabSelling Product` p JOIN `tabPOS Invoice Item` pii ON pii.item_code=p.item
	 JOIN `tabPOS Invoice` pi ON pi.name=pii.parent AND pi.docstatus=1 AND pi.is_return=0
	 JOIN `tabPOS Order Item` oi ON oi.name=pii.rms_pos_order_item
	 JOIN `tabPOS Order` o ON o.name=oi.parent
	 WHERE pi.company=%(company)s AND o.store IN %(stores)s AND pi.posting_date<=%(to_date)s
	 GROUP BY p.name""")
	last_map = {r.product: r.last_sale for r in last}
	result = []
	for p in catalog(ctx):
		last_sale = last_map.get(p.name)
		reference = last_sale or p.creation
		elapsed = date_diff(ctx.to_date, getdate(reference))
		if elapsed >= days:
			result.append(
				dict(
					product=p.name,
					title=p.title,
					category=p.product_category,
					enabled=p.enabled,
					last_sale=last_sale,
					days_without_sale=elapsed,
					currency=ctx.currency,
				)
			)
	return [
		col("product", "Selling Product", "Link", "Selling Product", 180),
		col("title", "Product Name", "Data", width=190),
		col("category", "Product Category", "Link", "Product Category"),
		col("enabled", "Enabled", "Check"),
		col("last_sale", "Last Sale", "Date"),
		col("days_without_sale", "Days Without Sales", "Int"),
	], result


def price_impact(facts, currency):
	groups = {}
	for r in facts:
		if r.get("is_return"):
			continue
		g = groups.setdefault(
			r["product"],
			dict(
				label=r["product"],
				title=r.get("product_title") or r.get("item_name"),
				category=r.get("category"),
				quantity=0,
				reference_revenue=0,
				revenue=0,
				currency=currency,
			),
		)
		qty = flt(r.get("qty"))
		reference = flt(r.get("base_price_list_rate"))
		g["quantity"] += qty
		g["reference_revenue"] += reference * qty if reference else flt(r.get("base_amount"))
		g["revenue"] += r["revenue"]
	for g in groups.values():
		g["reference_price"] = g["reference_revenue"] / g["quantity"] if g["quantity"] else None
		g["realized_price"] = g["revenue"] / g["quantity"] if g["quantity"] else None
		g["price_impact"] = g["revenue"] - g["reference_revenue"]
		g["impact_percent"] = (
			g["price_impact"] / g["reference_revenue"] * 100 if g["reference_revenue"] else None
		)
	return [
		col("label", "Selling Product", "Link", "Selling Product", 180),
		col("title", "Product Name", "Data", width=185),
		col("quantity", "Quantity Sold", "Float"),
		col("reference_price", "Reference Unit Price"),
		col("realized_price", "Realized Unit Price"),
		col("reference_revenue", "Reference Revenue"),
		col("revenue", "Net Revenue"),
		col("price_impact", "Price Impact"),
		col("impact_percent", "Price Impact %", "Percent"),
	], list(groups.values())


def consumption(ctx, facts):
	from rms.analytics.costs import attach_actual_costs

	attach_actual_costs(ctx, facts)
	groups = {}
	include_modifiers = (
		cint(ctx.filters.include_modifiers) if ctx.filters.include_modifiers is not None else 1
	)
	for r in facts:
		if r.get("is_modifier") and not include_modifiers:
			continue
		if r.get("is_return") and r.get("waste_return"):
			continue
		if r.get("cost") is None:
			continue
		components = [
			c
			for c in parse_json_rows(r.get("recipe_snapshot"))
			if c.get("source_selling_product") == r.get("product")
		]
		if not components and not r.get("is_modifier"):
			old = parse_json_rows(r.get("recipe_snapshot"))
			if old and not any(c.get("source_selling_product") for c in old):
				components = old
		denominator = flt(r.get("order_qty"))
		if r.get("is_modifier"):
			denominator *= sum(
				flt(m.get("qty") or 1)
				for m in parse_json_rows(r.get("modifiers"))
				if m.get("modifier_product") == r.get("product")
			)

		if not denominator:
			continue
		for c in components:
			if names(ctx.filters.item) and c.item not in names(ctx.filters.item):
				continue
			key = (c.item, c.warehouse, c.uom)
			g = groups.setdefault(
				key,
				dict(
					item=c.item,
					warehouse=c.warehouse,
					uom=c.uom,
					consumed_qty=0,
					restored_qty=0,
					waste_qty=0,
					currency=ctx.currency,
				),
			)
			qty = flt(c.qty) * flt(r.get("qty")) / denominator
			if qty < 0:
				g["restored_qty"] -= qty
			else:
				g["consumed_qty"] += qty
	if cint(ctx.filters.include_waste):
		if any(
			ctx.filters.get(key)
			for key in ("product", "category", "brand", "order_type", "customer", "cashier")
		) or any(ctx.scopes.values()):
			frappe.throw(
				_(
					"Clear product, customer, cashier, brand and order type filters before including unattributed waste."
				)
			)
		rows = ctx.query("""SELECT sle.item_code AS item,sle.warehouse,sle.stock_uom AS uom,
		 -SUM(sle.actual_qty) AS qty FROM `tabStock Ledger Entry` sle
		 JOIN `tabStock Entry` se ON se.name=sle.voucher_no AND sle.voucher_type='Stock Entry'
		 WHERE sle.company=%(company)s AND sle.is_cancelled=0 AND se.docstatus=1
		 AND se.stock_entry_type='Void' AND sle.posting_date BETWEEN %(from_date)s AND %(to_date)s
		 AND (EXISTS(SELECT 1 FROM `tabWaste Entry` w WHERE w.stock_entry=se.name AND w.store IN %(stores)s)
		 OR EXISTS(SELECT 1 FROM `tabPOS Order Item Cancellation` c JOIN `tabPOS Order` o ON o.name=c.parent WHERE c.waste_stock_entry=se.name AND o.store IN %(stores)s))
		 GROUP BY sle.item_code,sle.warehouse,sle.stock_uom""")
		for r in rows:
			if names(ctx.filters.item) and r.item not in names(ctx.filters.item):
				continue
			g = groups.setdefault(
				(r.item, r.warehouse, r.uom),
				dict(
					item=r.item,
					warehouse=r.warehouse,
					uom=r.uom,
					consumed_qty=0,
					restored_qty=0,
					waste_qty=0,
					currency=ctx.currency,
				),
			)
			g["waste_qty"] += flt(r.qty)
	for g in groups.values():
		g["net_qty"] = g["consumed_qty"] - g["restored_qty"] + g["waste_qty"]
	return [
		col("item", "Ingredient", "Link", "Item", 185),
		col("warehouse", "Warehouse", "Link", "Warehouse", 180),
		col("uom", "Stock UOM", "Link", "UOM"),
		col("consumed_qty", "Consumed Quantity", "Float"),
		col("restored_qty", "Returned Quantity", "Float"),
		col("waste_qty", "Waste Quantity", "Float"),
		col("net_qty", "Net Consumption", "Float"),
	], list(groups.values())


def availability(ctx):
	from rms.analytics.inventory import movement, stock_columns

	# Ingredient filtering chooses recipes, never removes the other ingredients
	# needed to calculate their limiting stock balance.
	stock_ctx = copy(ctx)
	stock_ctx.filters = frappe._dict(ctx.filters)
	if cint(ctx.filters.include_recipe):
		stock_ctx.filters.item = None
		stock_ctx.filters.item_group = None
	balances = movement(stock_ctx)
	for r in balances:
		r["unit_value"] = r["balance_value"] / r["balance_qty"] if r["balance_qty"] else None
	cols = stock_columns() + [
		col("balance_qty", "Available Quantity", "Float"),
		col("balance_value", "Stock Value"),
		col("unit_value", "Unit Value"),
	]
	if not cint(ctx.filters.include_recipe):
		return cols, balances
	planner = Planning(ctx)
	stock = {(r["item"], r["warehouse"]): flt(r["balance_qty"]) for r in balances}
	rows = []
	order_type = names(ctx.filters.order_type)
	for p in catalog(ctx):
		if not p.with_recipe:
			continue
		product = frappe.get_cached_doc("Selling Product", p.name)
		components = planner.components(product, order_type[0] if len(order_type) == 1 else None)
		# Shared ingredients in a recipe must be combined before capacity is computed.
		needed = defaultdict(float)
		for c in components:
			needed[c["item"]] += flt(c["qty"])
		if names(ctx.filters.item) and not set(needed).intersection(names(ctx.filters.item)):
			continue
		if ctx.filters.item_group:
			from rms.analytics.inventory import matches_item

			if not any(
				matches_item(
					ctx, {"item": item, "item_group": frappe.get_cached_value("Item", item, "item_group")}
				)
				for item in needed
			):
				continue
		for warehouse in ctx.warehouse_scope():
			capacity = min(
				(
					stock.get((item, warehouse), 0) / quantity
					for item, quantity in needed.items()
					if quantity > 0
				),
				default=None,
			)
			if capacity is not None:
				capacity = max(capacity, 0)
				if frappe.get_cached_value("UOM", product.uom, "must_be_whole_number"):
					capacity = math.floor(capacity)
			rows.append(
				dict(
					product=p.name,
					title=p.title,
					category=p.product_category,
					warehouse=warehouse,
					available_products=capacity,
					uom=p.uom,
					currency=ctx.currency,
				)
			)
	return [
		col("product", "Selling Product", "Link", "Selling Product", 185),
		col("title", "Product Name", "Data", width=185),
		col("warehouse", "Warehouse", "Link", "Warehouse", 185),
		col("available_products", "Recipe Capacity", "Float"),
		col("uom", "UOM", "Link", "UOM"),
	], rows


def daily_operations(ctx, facts):
	if ctx.from_date != ctx.to_date:
		frappe.throw(_("Choose one business day for Daily Operations."))
	orders = ctx.query("""SELECT o.name,o.status,o.grand_total,o.restaurant_brand AS brand,o.order_type,o.customer,o.dining_area,o.dining_table
	 FROM `tabPOS Order` o JOIN `tabStore` s ON s.name=o.store WHERE s.company=%(company)s
	 AND o.store IN %(stores)s AND o.business_date=%(from_date)s""")
	orders = [r for r in orders if ctx.accepts(r)]
	open_orders = [r for r in orders if r.status not in {"Paid", "Cancelled"}]
	sessions = ctx.query("""SELECT cs.name,cs.status,cs.user,cs.store FROM `tabCashier Session` cs
	 WHERE cs.store_company=%(company)s AND cs.store IN %(stores)s AND cs.business_date=%(from_date)s""")
	if cint(ctx.filters.closed_day_only) and (open_orders or any(s.status != "Closed" for s in sessions)):
		frappe.throw(_("This business day still has open orders or cashier sessions."))
	result = []
	for label, amount in [
		("Gross Revenue", sum(r["gross_revenue"] for r in facts)),
		("Allocated Discount", sum(r["allocated_discount"] for r in facts)),
		("Net Revenue", sum(r["revenue"] for r in facts)),
		("Taxes", sum(r["tax"] for r in facts)),
		("Net Collected", sum(r["collected"] for r in facts)),
		("Rounding Difference", sum(r["rounding"] for r in facts)),
	]:
		result.append(dict(section=_("Sales"), metric=_(label), amount=amount, currency=ctx.currency))
	from rms.analytics.sales import payment_rows

	for r in payment_rows(ctx, facts):
		result.append(
			dict(
				section=_("Payments"),
				metric=r["label"],
				amount=r["amount"],
				count=r["invoice_count"],
				currency=ctx.currency,
			)
		)
	expenses = []
	if frappe.has_permission("Shift Expense", "report"):
		expenses = ctx.query("""SELECT name AS expense,store,mode_of_payment,expense_account AS account,cost_center,amount
		 FROM `tabShift Expense` WHERE company=%(company)s AND store IN %(stores)s
		 AND business_date=%(from_date)s AND status='Posted' AND docstatus=1""")
	groups = {}
	for r in expenses:
		g = groups.setdefault(r.mode_of_payment, dict(amount=0, count=0))
		g["amount"] += flt(r.amount)
		g["count"] += 1
	for method, r in groups.items():
		result.append(
			dict(
				section=_("Posted Expenses"),
				metric=method,
				amount=r["amount"],
				count=r["count"],
				currency=ctx.currency,
			)
		)

	result.append(
		dict(
			section=_("Operations"),
			metric=_("Open Orders"),
			count=len(open_orders),
			amount=sum(flt(r.grand_total) for r in open_orders),
			currency=ctx.currency,
		)
	)
	result.append(
		dict(
			section=_("Operations"),
			metric=_("Open Sessions"),
			count=sum(s.status != "Closed" for s in sessions),
			currency=ctx.currency,
		)
	)
	return [
		col("section", "Section", "Data", width=160),
		col("metric", "Metric", "Data", width=240),
		col("count", "Count", "Int"),
		col("amount", "Amount"),
	], result
