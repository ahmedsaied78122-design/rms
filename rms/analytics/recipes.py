"""Read-only catalog costing and ingredient trace using RMS recipe semantics."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, flt

from rms.analytics.context import names, limited
from rms.analytics.sales import col
from rms.recipe import get_additional_recipe_order_types


class Planning:
	def __init__(self, ctx):
		self.ctx = ctx
		self.items = {}
		self.boms = {}

	def item(self, code):
		if code not in self.items:
			self.items[code] = frappe.db.get_value(
				"Item",
				code,
				["item_name", "item_group", "stock_uom", "valuation_rate", "is_stock_item", "disabled"],
				as_dict=True,
			)
		return self.items[code]

	def expand(self, code, quantity, multi=False, path=()):
		if code in path:
			frappe.throw(_("Circular Sub Recipe detected for Item {0}.").format(code))
		if code not in self.boms:
			boms = frappe.get_all(
				"BOM",
				filters={"item": code, "is_active": 1, "docstatus": 1},
				pluck="name",
				order_by="is_default desc, creation desc",
				limit_page_length=1,
			)
			self.boms[code] = frappe.get_cached_doc("BOM", boms[0]) if boms else None
		bom = self.boms[code]
		if not bom:
			frappe.throw(_("No active submitted BOM exists for Sub Recipe Item {0}.").format(code))
		result = []
		for row in bom.items:
			qty = flt(row.stock_qty or row.qty) * quantity / (flt(bom.quantity) or 1)
			if multi and frappe.db.exists("BOM", {"item": row.item_code, "is_active": 1, "docstatus": 1}):
				result.extend(self.expand(row.item_code, qty, True, path + (code,)))
			else:
				result.append(self.component(row.item_code, qty))
		return result

	def component(self, code, quantity):
		i = self.item(code)
		if not i:
			frappe.throw(_("Recipe component does not exist."))
		return dict(
			item=code,
			item_name=i.item_name,
			item_group=i.item_group,
			uom=i.stock_uom,
			qty=quantity,
			unit_cost=flt(i.valuation_rate),
			cost=flt(i.valuation_rate) * quantity,
		)

	def components(self, product, order_type=None):
		result = []
		if not product.with_recipe:
			return result
		for row in product.recipe:
			if row.sub_recipe:
				result.extend(self.expand(row.item, flt(row.qty), bool(row.multi_level)))
			else:
				result.append(self.component(row.item, flt(row.qty)))
		if order_type:
			for row in product.additional_recipe:
				if order_type in get_additional_recipe_order_types(row.order_types):
					result.append(self.component(row.item, flt(row.qty)))
		return result

	def unit_cost(self, product, order_type=None):
		if product.with_recipe:
			return sum(c["cost"] for c in self.components(product, order_type))
		if product.maintain_stock:
			item = self.item(product.item)
			return flt(item.valuation_rate) if item else None
		return 0


def catalog(ctx):
	filters = {"has_options": 0}
	if ctx.filters.enabled not in (None, ""):
		filters["enabled"] = cint(ctx.filters.enabled)
	if ctx.categories:
		filters["product_category"] = ["in", ctx.categories]
	if names(ctx.filters.product):
		filters["name"] = ["in", names(ctx.filters.product)]
	rows = limited(
		frappe.get_all(
			"Selling Product",
			filters=filters,
			fields=[
				"name",
				"creation",
				"title",
				"product_category",
				"selling_price",
				"enabled",
				"with_recipe",
				"maintain_stock",
				"is_modifier",
				"can_be_sold_separately",
				"item",
				"uom",
			],
			order_by="title asc",
			limit_page_length=50001,
		)
	)
	# Empty availability means all stores, otherwise an explicit allowlist.
	availability = defaultdict(set)
	for row in frappe.get_all(
		"Selling Product Store Availability",
		fields=["parent", "store"],
		filters={"parenttype": "Selling Product"},
	):
		availability[row.parent].add(row.store)
	rows = [r for r in rows if not availability[r.name] or set(ctx.stores) & availability[r.name]]
	for r in rows:
		r["product"] = r.name
		r["category"] = r.product_category
	return ctx.guard(rows)


def plan(ctx, family):
	planner = Planning(ctx)
	data = []
	store = names(ctx.filters.store)
	order_type = names(ctx.filters.order_type)
	brand = names(ctx.filters.brand)
	for row in catalog(ctx):
		if family == "no_recipe" and row.with_recipe:
			continue
		if family == "planned_margin" and not row.with_recipe:
			continue
		p = frappe.get_cached_doc("Selling Product", row.name)
		rate = p.selling_price
		if len(store) == 1:
			resolved = p.resolve_price(
				store[0],
				order_type[0] if len(order_type) == 1 else None,
				brand[0] if len(brand) == 1 else None,
				strict=False,
			)
			rate = resolved["selling_price"] if resolved else None
		cost = planner.unit_cost(p, order_type[0] if len(order_type) == 1 else None)
		base = dict(
			product=p.name,
			title=p.title,
			category=p.product_category,
			enabled=p.enabled,
			selling_price=rate,
			cost=cost,
			currency=ctx.currency,
			maintain_stock=p.maintain_stock,
			with_recipe=p.with_recipe,
			uom=p.uom,
		)
		base["gross_profit"] = flt(rate) - cost if rate is not None and cost is not None else None
		base["margin_percent"] = (
			base["gross_profit"] / rate * 100 if rate and base["gross_profit"] is not None else None
		)
		if family == "ingredients":
			requested = names(ctx.filters.item)
			for component in planner.components(p, order_type[0] if len(order_type) == 1 else None):
				if not requested or component["item"] in requested:
					data.append({**base, **component})
			# Show order-specific packaging even when no order type was selected.
			if not order_type:
				for extra in p.additional_recipe:
					if not requested or extra.item in requested:
						data.append(
							{
								**base,
								**planner.component(extra.item, flt(extra.qty)),
								"order_types": ", ".join(
									get_additional_recipe_order_types(extra.order_types)
								),
							}
						)
		elif family == "scenarios":
			data.extend(scenarios(ctx, planner, p, base, order_type[0] if len(order_type) == 1 else None))
		else:
			data.append(base)
	return data


def scenarios(ctx, planner, product, base, order_type=None):
	result = [{**base, "scenario": _("Base Product"), "modifier_group": None, "modifier_product": None}]
	options = defaultdict(list)
	for option in product.modifier_options:
		options[option.modifier_group].append(option)
	minimum_extra_price = maximum_extra_price = minimum_extra_cost = maximum_extra_cost = 0
	costs_known = base["cost"] is not None
	for group in product.modifier_groups:
		choices = []
		for option in options[group.modifier_group]:
			modifier = frappe.get_doc("Selling Product", option.modifier_product)
			cost = planner.unit_cost(modifier, order_type)
			choices.append((flt(option.selling_price), cost or 0))
			costs_known = costs_known and cost is not None
			selling = (
				flt(base["selling_price"]) + flt(option.selling_price)
				if base["selling_price"] is not None
				else None
			)
			total_cost = (
				flt(base["cost"]) + flt(cost) if base["cost"] is not None and cost is not None else None
			)
			profit = selling - total_cost if selling is not None and total_cost is not None else None
			result.append(
				{
					**base,
					"scenario": _("One Modifier"),
					"modifier_group": group.modifier_group,
					"modifier_product": option.modifier_product,
					"selling_price": selling,
					"cost": total_cost,
					"gross_profit": profit,
					"margin_percent": profit / selling * 100 if selling and profit is not None else None,
				}
			)
		minimum = cint(group.min_selections)
		maximum = min(cint(group.max_selections) or len(choices), len(choices))
		for index, kind in [(0, "price"), (1, "cost")]:
			values = sorted(c[index] for c in choices)
			# Optional negative-price choices can lower the minimum beyond the minimum count.
			lowest = min((sum(values[:n]) for n in range(minimum, maximum + 1)), default=0)
			highest = max((sum(values[::-1][:n]) for n in range(minimum, maximum + 1)), default=0)
			if kind == "price":
				minimum_extra_price += lowest
				maximum_extra_price += highest
			else:
				minimum_extra_cost += lowest
				maximum_extra_cost += highest
	result.append(
		{
			**base,
			"scenario": _("Selection Range"),
			"minimum_price": flt(base["selling_price"]) + minimum_extra_price
			if base["selling_price"] is not None
			else None,
			"maximum_price": flt(base["selling_price"]) + maximum_extra_price
			if base["selling_price"] is not None
			else None,
			"minimum_cost": flt(base["cost"]) + minimum_extra_cost if costs_known else None,
			"maximum_cost": flt(base["cost"]) + maximum_extra_cost if costs_known else None,
		}
	)
	return result


def recipe_columns(family):
	cols = [
		col("product", "Selling Product", "Link", "Selling Product", 175),
		col("title", "Product Name", "Data", width=185),
		col("category", "Product Category", "Link", "Product Category"),
		col("enabled", "Enabled", "Check"),
	]
	if family == "ingredients":
		return cols + [
			col("item", "Item", "Link", "Item"),
			col("item_name", "Item Name", "Data", width=180),
			col("qty", "Quantity per Product", "Float"),
			col("uom", "UOM", "Link", "UOM"),
			col("order_types", "Order Types", "Data", width=180),
			col("unit_cost", "Current Unit Cost"),
			col("cost", "Ingredient Cost"),
		]
	if family == "no_recipe":
		return cols + [
			col("maintain_stock", "Maintain Stock", "Check"),
			col("uom", "UOM", "Link", "UOM"),
			col("selling_price", "Default Selling Price"),
		]
	if family == "scenarios":
		cols.extend(
			[
				col("scenario", "Scenario", "Data", width=160),
				col("modifier_group", "Modifier Group", "Link", "Modifier Group"),
				col("modifier_product", "Modifier Product", "Link", "Selling Product"),
			]
		)
	cols.extend(
		[
			col("selling_price", "Planned Selling Price"),
			col("cost", "Planned Cost"),
			col("gross_profit", "Planned Gross Profit"),
			col("margin_percent", "Planned Margin %", "Percent"),
		]
	)
	if family == "scenarios":
		cols.extend(
			[
				col("minimum_price", "Minimum Price"),
				col("maximum_price", "Maximum Price"),
				col("minimum_cost", "Minimum Cost"),
				col("maximum_cost", "Maximum Cost"),
			]
		)
	return cols
