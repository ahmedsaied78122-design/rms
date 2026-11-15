"""Cost actual posted movements; never substitute today's valuation for history."""

from collections import defaultdict

from frappe.utils import flt

from rms.snapshots import parse_json_rows


def attach_actual_costs(ctx, facts):
	if not facts:
		return facts
	invoice_items = [r["invoice_item"] for r in facts]
	stock = ctx.query(
		"""SELECT sii.pos_invoice_item AS invoice_item,
	 -SUM(sle.stock_value_difference) AS cost_amount
	 FROM `tabSales Invoice Item` sii
	 JOIN `tabSales Invoice` si ON si.name = sii.parent AND si.docstatus = 1
	 JOIN `tabStock Ledger Entry` sle ON sle.voucher_type = 'Sales Invoice'
	  AND sle.voucher_detail_no = sii.name AND sle.voucher_no = si.name AND sle.is_cancelled = 0
	 WHERE si.company = %(company)s AND sii.pos_invoice_item IN %(invoice_items)s
	 GROUP BY sii.pos_invoice_item""",
		{"invoice_items": invoice_items},
	)
	stock_cost = {r.invoice_item: flt(r.cost_amount) for r in stock}
	returns = ctx.query(
		"""SELECT return_pos_invoice AS invoice, stock_entry, is_waste FROM `tabPOS Return`
	 WHERE status = 'Approved' AND docstatus < 2 AND return_pos_invoice IN %(invoices)s
	 AND store IN %(stores)s""",
		{"invoices": list({r["invoice"] for r in facts if r.get("is_return")}) or [""]},
	)
	return_map = {r.invoice: r for r in returns}
	entries = {r.get("recipe_stock_entry") for r in facts if r.get("recipe_stock_entry")}
	entries.update(r.stock_entry for r in returns if r.stock_entry)
	units = {}
	if entries:
		ledger = ctx.query(
			"""SELECT voucher_no, item_code, warehouse, SUM(actual_qty) AS movement_qty,
		 SUM(stock_value_difference) AS movement_value FROM `tabStock Ledger Entry`
		 WHERE voucher_type = 'Stock Entry' AND voucher_no IN %(entries)s
		 AND company = %(company)s AND is_cancelled = 0
		 GROUP BY voucher_no, item_code, warehouse""",
			{"entries": list(entries)},
		)
		units = {
			(r.voucher_no, r.item_code, r.warehouse): flt(r.movement_value) / flt(r.movement_qty)
			for r in ledger
			if flt(r.movement_qty)
		}
	for row in facts:
		row["cost"] = None
		returned = return_map.get(row["invoice"]) if row.get("is_return") else None
		if returned and returned.is_waste:
			row["cost"] = 0
			row["waste_return"] = True
		elif (
			returned
			and row.get("maintain_stock")
			and (returned.stock_entry, row.get("item_code"), row.get("warehouse")) in units
		):
			row["cost"] = (
				flt(row.get("stock_qty"))
				* units[(returned.stock_entry, row.get("item_code"), row.get("warehouse"))]
			)
		elif row.get("invoice_item") in stock_cost:
			row["cost"] = stock_cost[row["invoice_item"]]
		elif row.get("with_recipe"):
			entry = row.get("recipe_stock_entry")
			returned = return_map.get(row["invoice"])
			if row.get("is_return"):
				if returned and returned.is_waste:
					row["cost"] = 0
					row["valuation_status"] = "Posted"
					continue
				entry = returned.stock_entry if returned else None
			components = [
				c
				for c in parse_json_rows(row.get("recipe_snapshot"))
				if c.get("source_selling_product") == row.get("product")
			]
			# Legacy mixed snapshots cannot safely attribute a modifier to its parent.
			if not components and not row.get("is_modifier"):
				all_components = parse_json_rows(row.get("recipe_snapshot"))
				if all_components and not any(c.get("source_selling_product") for c in all_components):
					components = all_components
			per_order_qty = flt(row.get("order_qty"))
			if row.get("is_modifier"):
				per_order_qty *= sum(
					flt(m.get("qty") or 1)
					for m in parse_json_rows(row.get("modifiers"))
					if m.get("modifier_product") == row.get("product")
				)

			if (
				entry
				and components
				and per_order_qty
				and all((entry, c.item, c.warehouse) in units for c in components)
			):
				row["cost"] = (
					sum(flt(c.qty) * units[(entry, c.item, c.warehouse)] for c in components)
					* flt(row.get("qty"))
					/ per_order_qty
				)
		elif not row.get("maintain_stock"):
			row["cost"] = 0
		row["valuation_status"] = "Posted" if row["cost"] is not None else "Pending Valuation"
	return facts


def margin_rows(facts, group, currency):
	from rms.analytics.sales import aggregate, dimension

	base = aggregate(facts, group, currency)
	groups = defaultdict(list)
	for r in facts:
		groups[dimension(r, group)].append(r)
	for r in base:
		source = groups[r["group_key"]]
		missing = [x for x in source if x.get("cost") is None]
		r["unvalued_lines"] = len(missing)
		r["cost"] = None if missing else sum(flt(x.get("cost")) for x in source)
		r["gross_profit"] = r["revenue"] - r["cost"] if r["cost"] is not None else None
		r["margin_percent"] = (
			r["gross_profit"] / r["revenue"] * 100 if r["gross_profit"] is not None and r["revenue"] else None
		)
		r["unit_profit"] = (
			r["gross_profit"] / r["quantity"] if r["gross_profit"] is not None and r["quantity"] else None
		)
	return base


def engineer(rows):
	eligible = [r for r in rows if r.get("gross_profit") is not None and r["quantity"] > 0]
	total_qty = sum(r["quantity"] for r in eligible)
	average_qty = total_qty / len(eligible) if eligible else 0
	weighted_profit = sum(r["gross_profit"] for r in eligible) / total_qty if total_qty else 0
	for r in rows:
		r["sales_mix"] = r["quantity"] / total_qty * 100 if total_qty and r in eligible else None
		if r not in eligible:
			r["classification"] = (
				"Pending Valuation" if r.get("gross_profit") is None else "No Positive Sales"
			)
			continue
		high_volume = r["quantity"] >= average_qty
		high_margin = r["gross_profit"] / r["quantity"] >= weighted_profit
		r["classification"] = (
			("Star" if high_margin else "Volume Driver")
			if high_volume
			else ("Opportunity" if high_margin else "Review")
		)
	return rows
