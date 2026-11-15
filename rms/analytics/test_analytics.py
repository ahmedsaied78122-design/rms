import json
import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from rms.analytics.catalog import REPORTS
from rms.analytics.context import Context, names
from rms.analytics.costs import attach_actual_costs, margin_rows, engineer
from rms.analytics.inventory import price_changes
from rms.analytics.operations import overlap_minutes, working_windows
from rms.analytics.runner import compare_rows
from rms.analytics.sales import normalize_fact, aggregate, payment_rows, chart


def fact(**overrides):
	raw = dict(
		invoice="INV-1",
		invoice_item="LINE-1",
		is_return=0,
		business_date=date(2026, 11, 10),
		posting_time="12:00:00",
		product="P",
		parent_product="P",
		item_code="I",
		parent_item="I",
		category="C",
		store="S",
		brand="B",
		order_type="OT",
		customer="CUSTOMER",
		qty=1,
		stock_qty=1,
		base_net_amount=100,
		base_amount=100,
		base_net_total=100,
		base_grand_total=114,
		base_total_taxes_and_charges=14,
		base_paid_amount=120,
		base_change_amount=6,
		absolute_qty=1,
		recipe_snapshot="[]",
	)
	raw.update(overrides)
	return normalize_fact(raw, "EGP")


class TestAccountingFacts(unittest.TestCase):
	def test_invoice_tax_and_tender_are_allocated_once_across_lines(self):
		rows = [
			fact(base_net_amount=40, base_amount=40),
			fact(invoice_item="LINE-2", base_net_amount=60, base_amount=60),
		]
		self.assertAlmostEqual(sum(r["tax"] for r in rows), 14)
		self.assertAlmostEqual(sum(r["collected"] for r in rows), 114)
		self.assertAlmostEqual(sum(r["rounding"] for r in rows), 0)
		group = aggregate(rows, "store", "EGP")[0]
		self.assertEqual(group["invoice_count"], 1)
		self.assertEqual(group["revenue"], 100)

	def test_guest_invoices_count_separately_without_repeating_order_total(self):
		rows = [
			fact(
				invoice="GUEST-1",
				base_net_amount=40,
				base_net_total=40,
				base_amount=40,
				base_total_taxes_and_charges=5.6,
				base_grand_total=45.6,
				base_paid_amount=45.6,
				base_change_amount=0,
			),
			fact(
				invoice="GUEST-2",
				base_net_amount=60,
				base_net_total=60,
				base_amount=60,
				base_total_taxes_and_charges=8.4,
				base_grand_total=68.4,
				base_paid_amount=68.4,
				base_change_amount=0,
			),
		]
		group = aggregate(rows, "store", "EGP")[0]
		self.assertEqual(group["invoice_count"], 2)
		self.assertAlmostEqual(group["collected"], 114)

	def test_credit_note_signs_are_retained(self):
		r = fact(
			is_return=1,
			qty=-1,
			stock_qty=-1,
			base_net_amount=-100,
			base_amount=-100,
			base_net_total=-100,
			base_grand_total=-114,
			base_total_taxes_and_charges=-14,
			base_paid_amount=-114,
			base_change_amount=0,
		)
		self.assertEqual((r["revenue"], r["tax"], r["collected"]), (-100, -14, -114))
		g = aggregate([fact(), r], "store", "EGP")[0]
		self.assertEqual((g["invoice_count"], g["return_count"], g["revenue"]), (1, 1, 0))

	def test_actual_tax_on_a_free_invoice_uses_quantity_weights(self):
		rows = [
			fact(base_net_amount=0, base_net_total=0, base_amount=0, qty=1, absolute_qty=3),
			fact(base_net_amount=0, base_net_total=0, base_amount=0, qty=2, absolute_qty=3),
		]
		self.assertAlmostEqual(sum(r["tax"] for r in rows), 14)

	def test_modifier_revenue_is_not_counted_as_another_main_product(self):
		r = fact(product="M", item_code="MODIFIER", base_net_amount=5, base_amount=5, recipe_snapshot="[]")
		self.assertEqual(r["quantity"], 0)
		self.assertEqual(r["modifier_quantity"], 1)
		self.assertEqual(r["revenue"], 5)

	def test_saved_recipe_outweighs_current_recipe_flag(self):
		r = fact(
			with_recipe=0, recipe_snapshot=json.dumps([dict(item="ING", qty=1, source_selling_product="P")])
		)
		self.assertEqual(r["with_recipe"], 1)
		r = fact(with_recipe=1, recipe_snapshot="[]")
		self.assertEqual(r["with_recipe"], 0)

	def test_legacy_modifier_identity_comes_from_its_saved_item_link(self):
		r = fact(
			product=None,
			item_code="M-I",
			modifiers=json.dumps([dict(item="M-I", modifier_product="SAVED-M")]),
		)
		self.assertEqual(r["product"], "SAVED-M")

	def test_mixed_tender_change_is_removed_from_cash_first(self):
		ctx = SimpleNamespace(
			currency="EGP",
			query=lambda *a, **k: [
				frappe._dict(invoice="INV-1", mode_of_payment="Card", base_amount=50, payment_type="Bank"),
				frappe._dict(invoice="INV-1", mode_of_payment="Cash", base_amount=70, payment_type="Cash"),
			],
		)
		rows = payment_rows(ctx, [fact()])
		by = {r["label"]: r["amount"] for r in rows}
		self.assertEqual(by, {"Cash": 64, "Card": 50})

	def test_product_filter_tender_share_uses_full_invoice_denominator(self):
		ctx = SimpleNamespace(
			currency="EGP",
			query=lambda *a, **k: [
				frappe._dict(invoice="INV-1", mode_of_payment="Cash", base_amount=120, payment_type="Cash")
			],
		)
		rows = payment_rows(ctx, [fact(base_net_amount=25, base_amount=25)])
		self.assertAlmostEqual(rows[0]["amount"], 28.5)

	def test_pending_cost_is_not_plotted_as_zero_profit(self):
		result = chart(
			[dict(label="Pending", gross_profit=None), dict(label="Posted", gross_profit=12)], "gross_profit"
		)
		self.assertEqual(result["data"]["labels"], ["Posted"])
		self.assertEqual(result["data"]["datasets"][0]["values"], [12])

	def test_negative_payment_mix_uses_a_signed_chart(self):
		self.assertEqual(chart([dict(label="Refund", amount=-10)], "amount", kind="donut")["type"], "bar")


class TestPostedCostAttribution(unittest.TestCase):
	def test_recipe_uses_posted_cost_instead_of_snapshot_estimate(self):
		r = fact(
			order_qty=2,
			recipe_stock_entry="SE",
			with_recipe=1,
			recipe_snapshot=json.dumps(
				[dict(item="ING", qty=4, warehouse="W", cost=999, source_selling_product="P")]
			),
		)
		responses = [
			[],
			[],
			[
				frappe._dict(
					voucher_no="SE", item_code="ING", warehouse="W", movement_qty=-4, movement_value=-12
				)
			],
		]
		ctx = SimpleNamespace(query=lambda *a, **k: responses.pop(0))
		attach_actual_costs(ctx, [r])
		self.assertEqual(r["cost"], 6)

	def test_missing_movement_leaves_margin_blank(self):
		r = fact(maintain_stock=1, with_recipe=0)
		ctx = SimpleNamespace(query=lambda *a, **k: [])
		attach_actual_costs(ctx, [r])
		row = margin_rows([r], "product", "EGP")[0]
		self.assertIsNone(row["gross_profit"])
		self.assertEqual(row["unvalued_lines"], 1)

	def test_one_missing_line_does_not_produce_a_partial_group_profit(self):
		rows = [fact(), fact(invoice_item="L2")]
		rows[0]["cost"] = 10
		rows[1]["cost"] = None
		self.assertIsNone(margin_rows(rows, "category", "EGP")[0]["gross_profit"])

	def test_waste_return_does_not_reverse_consumed_cost(self):
		r = fact(
			is_return=1,
			qty=-1,
			with_recipe=1,
			recipe_stock_entry="SE",
			recipe_snapshot=json.dumps([dict(item="ING", qty=1, warehouse="W", source_selling_product="P")]),
		)
		responses = [
			[],
			[frappe._dict(invoice="INV-1", stock_entry=None, is_waste=1)],
			[
				frappe._dict(
					voucher_no="SE", item_code="ING", warehouse="W", movement_qty=-1, movement_value=-5
				)
			],
		]
		attach_actual_costs(SimpleNamespace(query=lambda *a, **k: responses.pop(0)), [r])
		self.assertEqual(r["cost"], 0)
		self.assertTrue(r["waste_return"])

	def test_engineering_thresholds_are_weighted_by_sold_units(self):
		rows = [dict(quantity=100, gross_profit=1000), dict(quantity=1, gross_profit=50)]
		out = engineer(rows)
		self.assertEqual(out[0]["classification"], "Volume Driver")
		self.assertEqual(out[1]["classification"], "Opportunity")


class TestPeriodAndStockMath(unittest.TestCase):
	def test_price_change_uses_stock_units_and_weighted_rates(self):
		current = [dict(item="I", stock_qty=2, value=20), dict(item="I", stock_qty=8, value=160)]
		previous = [dict(item="I", stock_qty=5, value=50)]
		r = price_changes(current, previous, "EGP")[0]
		self.assertEqual((r["average_rate"], r["previous_rate"], r["change_percent"]), (18, 10, 80))

	def test_new_purchase_item_has_no_fabricated_previous_price(self):
		r = price_changes([dict(item="I", stock_qty=2, value=20)], [], "EGP")[0]
		self.assertIsNone(r["previous_rate"])
		self.assertIsNone(r["change_percent"])

	def test_previous_day_buckets_are_shifted_by_period_length(self):
		current = [dict(group_key="2026-11-10", revenue=120)]
		old = [dict(group_key="2026-11-09", revenue=100)]
		r, _ = compare_rows(current, old, "sales", "date", 1)
		self.assertEqual(r[0]["change_percent"], 20)

	def test_zero_previous_value_has_no_infinite_growth_percentage(self):
		r, _ = compare_rows([dict(group_key="P", revenue=12)], [dict(group_key="P", revenue=0)], "sales")
		self.assertIsNone(r[0]["change_percent"])

	def test_overlapping_guest_checks_do_not_double_table_minutes(self):
		a = datetime(2026, 11, 10, 10)
		b = a + timedelta(hours=1)
		c = a + timedelta(hours=2)
		self.assertEqual(overlap_minutes([(a, b), (a + timedelta(minutes=30), c)], [(a, c)]), 120)

	def test_overnight_working_hours_are_clipped_to_the_period(self):
		rows = [dict(weekday="Monday", from_time="22:00:00", to_time="02:00:00", enabled=1)]
		windows = working_windows(rows, datetime(2026, 11, 10), datetime(2026, 11, 11))
		self.assertEqual(windows, [(datetime(2026, 11, 10), datetime(2026, 11, 10, 2))])


class TestReportPermissionBoundary(unittest.TestCase):
	def test_guest_is_rejected_before_metadata_queries(self):
		with patch("frappe.session", frappe._dict(user="Guest")), patch("frappe.get_roles") as roles:
			with self.assertRaises(frappe.PermissionError):
				Context(REPORTS["invoices"], {})
		roles.assert_not_called()

	def test_cashier_role_cannot_call_report_or_dashboard_engines(self):
		with (
			patch("frappe.session", frappe._dict(user="cashier@example.invalid")),
			patch("frappe.get_roles", return_value=["POS Cashier"]),
		):
			with self.assertRaises(frappe.PermissionError):
				Context(REPORTS["invoices"], {"company": "C"})

	def test_native_report_permission_is_required_in_addition_to_manager_role(self):
		with (
			patch("frappe.session", frappe._dict(user="manager@example.invalid")),
			patch("frappe.get_roles", return_value=["POS Manager"]),
			patch("frappe.has_permission", return_value=False),
		):
			with self.assertRaises(frappe.PermissionError):
				Context(REPORTS["invoices"], {"company": "C"})

	def test_explicit_pos_user_store_assignment_limits_system_manager_reports_too(self):
		ctx = Context.__new__(Context)
		ctx.company = "C"
		ctx.user = "u"
		ctx.roles = {"System Manager"}
		ctx.filters = frappe._dict(store="B")

		def records(dt, **kw):
			return [frappe._dict(name="A"), frappe._dict(name="B")] if dt == "Store" else ["A"]

		with (
			patch("frappe.get_all", side_effect=records),
			patch("frappe.db.get_value", return_value=frappe._dict(name="POSU", enabled=1)),
		):
			with self.assertRaises(frappe.PermissionError):
				ctx.allowed_stores()

	def test_brand_scope_rejects_another_brand_even_in_an_assigned_store(self):
		ctx = Context.__new__(Context)
		ctx.filters = frappe._dict()
		ctx.categories = []
		ctx.scopes = {"brand": {"A"}, "order_type": None}
		self.assertFalse(ctx.accepts({"brand": "B"}))
		self.assertTrue(ctx.accepts({"brand": "A"}))

	def test_filter_names_reject_objects_and_nested_values(self):
		for value in ({"x": "Y"}, ["A", {"x": "Y"}]):
			with self.assertRaises(frappe.ValidationError):
				names(value)

	def test_filter_names_deduplicate_without_losing_order(self):
		self.assertEqual(names('["B","A","B"]'), ["B", "A"])
