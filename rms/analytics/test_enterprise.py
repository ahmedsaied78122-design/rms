import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from rms.analytics.catalog import REPORTS
from rms.analytics.runner import compare_rows


class TestEnterpriseReports(unittest.TestCase):
	def test_same_modifier_in_two_groups_does_not_double_recipe_cost_or_consumption(self):
		from rms.analytics.test_analytics import fact
		from rms.analytics.costs import attach_actual_costs
		from rms.analytics.derived import consumption

		modifiers = json.dumps(
			[
				dict(modifier_product="M", modifier_group="G1", qty=1),
				dict(modifier_product="M", modifier_group="G2", qty=2),
			]
		)
		snapshot = json.dumps([dict(item="ING", warehouse="W", uom="Kg", qty=6, source_selling_product="M")])
		rows = [
			fact(
				product="M",
				parent_product="P",
				item_code="M-I",
				order_qty=1,
				qty=qty,
				invoice_item="L" + str(qty),
				recipe_stock_entry="SE",
				modifiers=modifiers,
				recipe_snapshot=snapshot,
			)
			for qty in (1, 2)
		]
		responses = [
			[],
			[],
			[
				frappe._dict(
					voucher_no="SE", item_code="ING", warehouse="W", movement_qty=-6, movement_value=-12
				)
			],
		]
		ctx = SimpleNamespace(query=lambda *a, **k: responses.pop(0), filters=frappe._dict(), currency="EGP")
		attach_actual_costs(ctx, rows)
		self.assertEqual([r["cost"] for r in rows], [4, 8])
		with patch("rms.analytics.costs.attach_actual_costs", side_effect=lambda ctx, facts: facts):
			_, data = consumption(ctx, rows)
		self.assertEqual(data[0]["consumed_qty"], 6)

	def test_missing_base_price_does_not_become_a_free_product_in_scenarios(self):
		from rms.analytics.recipes import scenarios

		product = frappe._dict(
			modifier_options=[frappe._dict(modifier_group="G", modifier_product="M", selling_price=5)],
			modifier_groups=[frappe._dict(modifier_group="G", min_selections=0, max_selections=1)],
		)
		with patch("frappe.get_doc", return_value=frappe._dict(name="M")):
			data = scenarios(
				None, SimpleNamespace(unit_cost=lambda *a: 2), product, dict(selling_price=None, cost=10)
			)
		self.assertIsNone(data[1]["selling_price"])
		self.assertIsNone(data[1]["gross_profit"])
		self.assertIsNone(data[-1]["minimum_price"])

	def test_ledger_item_annotations_do_not_multiply_financial_rows(self):
		from rms.analytics.enterprise import ledger

		rows = [frappe._dict(voucher_type="Purchase Invoice", voucher_no="P1", debit=40, credit=0)]
		ctx = SimpleNamespace(
			company="C",
			currency="EGP",
			from_date=date(2026, 11, 1),
			to_date=date(2026, 11, 10),
			filters=frappe._dict(),
			user="fixture",
			query=lambda *a, **k: [
				frappe._dict(parent="P1", item_code="A", item_name="A", qty=2, uom="Nos"),
				frappe._dict(parent="P1", item_code="B", item_name="B", qty=3, uom="Nos"),
			],
		)
		with (
			patch("erpnext.accounts.report.general_ledger.general_ledger.execute", return_value=([], rows)),
			patch(
				"frappe.desk.query_report.get_filtered_data", side_effect=lambda dt, cols, data, user: data
			),
			patch("frappe.has_permission", return_value=True),
			patch("frappe.get_list", return_value=["P1"]),
		):
			_, data = ledger(ctx)
		self.assertEqual(len(data), 1)
		self.assertEqual(data[0]["debit"], 40)
		self.assertIn("A · A", data[0]["item_details"])
		self.assertIn("B · B", data[0]["item_details"])

	def test_production_qty_and_completion_are_not_confused_with_process_loss(self):
		from rms.analytics.enterprise import production

		row = frappe._dict(
			planned_qty=10,
			produced_qty=8,
			process_loss_qty=1,
			warehouse="W",
			actual_operating_cost=45,
			planned_operating_cost=30,
			actual_end_date=date(2026, 11, 8),
			planned_end_date=date(2026, 11, 9),
		)
		ctx = SimpleNamespace(
			query=lambda *a, **k: [row], warehouse_scope=lambda: ["W"], filters=frappe._dict(), currency="EGP"
		)
		_, data = production(ctx)
		self.assertEqual(
			(
				data[0]["remaining_qty"],
				data[0]["completion_percent"],
				data[0]["loss_percent"],
				data[0]["on_time"],
			),
			(1, 80, 10, 1),
		)

	def test_overhead_balance_is_allocated_once_without_changing_posted_cost(self):
		from rms.analytics.enterprise import overhead

		results = [
			[frappe._dict(debit=40, credit=0)],
			[frappe._dict(item="I", item_name="I", uom="Nos", warehouse="W", quantity=2, cost=120)],
		]
		ctx = SimpleNamespace(
			filters=frappe._dict(account="A", cost_center="CC"),
			company="C",
			currency="EGP",
			warehouse_scope=lambda: ["W"],
			query=lambda *a, **k: results.pop(0),
		)

		def cached(dt, name, field):
			return "C" if field == "company" else "Expense"

		with (
			patch("frappe.get_cached_value", side_effect=cached),
			patch("frappe.has_permission", return_value=True),
			patch("frappe.db.get_value", return_value=frappe._dict(lft=1, rgt=2)),
			patch("frappe.get_list", return_value=["A", "CC"]),
		):
			_, data = overhead(ctx, True)
		self.assertEqual(
			(data[0]["cost"], data[0]["allocated_overhead"], data[0]["total_cost"], data[0]["unit_cost"]),
			(120, 40, 160, 80),
		)

	def test_explicit_brand_filter_outside_assigned_scope_is_rejected(self):
		from rms.analytics.context import Context

		with (
			patch("frappe.get_roles", return_value=["POS Manager"]),
			patch("frappe.has_permission", return_value=True),
			patch("frappe.get_cached_value", return_value="EGP"),
			patch.object(Context, "allowed_stores", return_value=["S"]),
			patch(
				"rms.api.pos.get_pos_user_scope_values",
				side_effect=lambda key: {"A"} if key == "brand" else None,
			),
		):
			with self.assertRaises(frappe.PermissionError):
				Context(REPORTS["planned_margin"], dict(company="C", brand="B"))

	def test_tender_shortfall_is_not_misreported_as_rounding(self):
		from rms.analytics.test_analytics import fact

		r = fact(base_paid_amount=100, base_change_amount=0, base_rounding_adjustment=0.1)
		self.assertAlmostEqual(r["rounding"], 0.1)

	def test_average_invoice_matches_cards_and_excludes_credit_notes(self):
		from rms.analytics.test_analytics import fact
		from rms.analytics.sales import aggregate

		credit = fact(
			is_return=1,
			qty=-1,
			base_net_amount=-100,
			base_grand_total=-114,
			base_net_total=-100,
			base_paid_amount=-114,
			base_change_amount=0,
		)
		row = aggregate([fact(), credit], "store", "EGP")[0]
		self.assertEqual(row["average_invoice"], 114)

	def test_disappeared_product_is_visible_as_a_decline(self):
		rows, _ = compare_rows([], [dict(group_key="P", label="P", revenue=100, gross_profit=20)], "sales")
		self.assertEqual(
			(rows[0]["revenue"], rows[0]["previous_value"], rows[0]["change_percent"]), (0, 100, -100)
		)

	def test_customer_cohorts_include_both_new_and_returning_customers(self):
		from rms.analytics.enterprise import customers

		rows = [
			frappe._dict(
				customer=c,
				customer_name=c,
				customer_group="G",
				posting_date=date(2026, 11, 10),
				first_purchase=first,
				is_return=0,
				total_qty=1,
				base_net_total=value,
				base_grand_total=value,
			)
			for c, first, value in [("NEW", date(2026, 11, 1), 100), ("OLD", date(2026, 10, 1), 200)]
		]
		ctx = SimpleNamespace(query=lambda *a, **k: rows, filters=frappe._dict(), currency="EGP")
		_, data = customers(ctx, True)
		self.assertEqual(
			(data[0]["new_revenue"], data[0]["repeat_revenue"], data[0]["customer_average"]), (100, 200, 150)
		)
		self.assertEqual((data[0]["new_customers"], data[0]["repeat_customers"]), (1, 1))

	def test_purchase_summary_uses_stock_units_company_currency_and_signed_returns(self):
		from rms.analytics.enterprise import purchases

		rows = [
			frappe._dict(
				purchase_invoice=invoice,
				supplier="S",
				item="I",
				uom="Kg",
				quantity=qty,
				value=value,
				warehouse="W",
				is_fixed_asset=0,
			)
			for invoice, qty, value in [("P1", 10, 100), ("P2", 5, 100), ("R1", -2, -20)]
		]
		ctx = SimpleNamespace(
			query=lambda *a, **k: rows, filters=frappe._dict(), currency="EGP", warehouse_scope=lambda: ["W"]
		)
		_, data = purchases(ctx, True)
		self.assertEqual((data[0]["quantity"], data[0]["value"], data[0]["invoice_count"]), (13, 180, 3))
		self.assertAlmostEqual(data[0]["unit_price"], 180 / 13)

	def test_group_warehouse_filters_use_expanded_leaves(self):
		from rms.analytics.inventory import purchase_facts

		ctx = SimpleNamespace(
			query=lambda *a, **k: [frappe._dict(item="I", warehouse="CHILD", supplier="S")],
			filters=frappe._dict(warehouse="GROUP"),
			warehouse_scope=lambda: ["CHILD"],
		)
		self.assertEqual(len(purchase_facts(ctx)), 1)

	def test_recipe_capacity_still_reads_other_ingredients_when_one_is_filtered(self):
		from rms.analytics.derived import availability

		seen = []

		def movement(ctx):
			seen.append(ctx.filters.item)
			return [
				dict(item="A", warehouse="W", balance_qty=10, balance_value=10),
				dict(item="B", warehouse="W", balance_qty=4, balance_value=4),
			]

		ctx = SimpleNamespace(
			filters=frappe._dict(item="A", include_recipe=1), warehouse_scope=lambda: ["W"], currency="EGP"
		)
		product = frappe._dict(name="P", title="P", with_recipe=1, product_category="C", uom="Nos")
		with (
			patch("rms.analytics.inventory.movement", side_effect=movement),
			patch("rms.analytics.derived.catalog", return_value=[product]),
			patch("rms.analytics.derived.Planning") as planner,
			patch("frappe.get_cached_doc", return_value=product),
			patch("frappe.get_cached_value", return_value=0),
		):
			planner.return_value.components.return_value = [dict(item="A", qty=1), dict(item="B", qty=2)]
			_, data = availability(ctx)
		self.assertEqual(seen, [None])
		self.assertEqual(data[0]["available_products"], 2)

	def test_return_refund_is_allocated_once_and_converted_to_company_currency(self):
		from rms.analytics.operations import returns

		rows = [
			frappe._dict(
				amount=value, total_amount=100, total_qty=2, qty=1, refund_total=114, conversion_rate=2
			)
			for value in [40, 60]
		]
		ctx = SimpleNamespace(query=lambda *a, **k: rows, accepts=lambda r: True, filters=frappe._dict())
		_, data = returns(ctx)
		self.assertAlmostEqual(sum(r["allocated_refund"] for r in data), 228)
		self.assertAlmostEqual(sum(r["amount"] for r in data), 200)

	def test_cancellation_value_includes_saved_modifiers(self):
		from rms.analytics.operations import cancellations

		rows = [frappe._dict(qty=2, selling_price=100, modifiers=json.dumps([dict(qty=2, selling_price=5)]))]
		ctx = SimpleNamespace(query=lambda *a, **k: rows, accepts=lambda r: True)
		_, data = cancellations(ctx)
		self.assertEqual(data[0]["cancelled_value"], 220)


class WorkspaceFixture:
	def __init__(self):
		self.content = '[{"id":"user-block","type":"header","data":{"text":"Keep me"}}]'
		self.links = [
			frappe._dict(type="Card Break", label="My links"),
			frappe._dict(type="Link", link_type="DocType", link_to="Item"),
		]
		self.charts = []
		self.number_cards = []
		self.saves = 0

	def append(self, field, row):
		row = frappe._dict(row)
		getattr(self, field).append(row)
		return row

	def save(self, **kwargs):
		self.saves += 1


class TestWorkspaceInstallation(unittest.TestCase):
	def test_second_install_preserves_user_blocks_and_does_not_duplicate_widgets(self):
		from rms.analytics.install import merge_workspace

		w = WorkspaceFixture()
		spec = REPORTS["invoices"]
		self.assertTrue(merge_workspace(w, [spec], ["My chart"], ["My card"]))
		snapshot = json.dumps([w.content, w.links, w.charts, w.number_cards], sort_keys=True)
		self.assertFalse(merge_workspace(w, [spec], ["My chart"], ["My card"]))
		self.assertEqual(json.dumps([w.content, w.links, w.charts, w.number_cards], sort_keys=True), snapshot)
		self.assertEqual(w.saves, 1)
		self.assertEqual(json.loads(w.content)[1]["id"], "user-block")

	def test_upgrade_places_new_links_inside_our_card_without_moving_user_cards(self):
		from rms.analytics.install import merge_workspace

		w = WorkspaceFixture()
		merge_workspace(w, [REPORTS["invoices"]])
		w.links.extend(
			[
				frappe._dict(type="Card Break", label="Later user card"),
				frappe._dict(type="Link", link_type="DocType", link_to="Customer"),
			]
		)
		merge_workspace(w, [REPORTS["invoices"], REPORTS["payments"]])
		payment = next(i for i, r in enumerate(w.links) if r.link_to == REPORTS["payments"]["name"])
		user = next(i for i, r in enumerate(w.links) if r.label == "Later user card")
		self.assertLess(payment, user)
		self.assertEqual(w.links[-1].link_to, "Customer")
