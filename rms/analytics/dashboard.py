"""Permission-scoped dashboard endpoints. No chart cache is shared across users."""

import json
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_months, getdate

from rms.analytics.catalog import CARD_METRICS, REPORTS
from rms.analytics.context import Context
from rms.analytics.runner import execute
from rms.analytics.sales import invoice_facts
from rms.utils import get_business_date


def parse_filters(value):
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except ValueError:
			frappe.throw(_("Invalid analytics filters."))
	if value is None:
		return {}
	if not isinstance(value, dict):
		frappe.throw(_("Invalid analytics filters."))
	return dict(value)


@frappe.whitelist()
def get_number(filters=None):
	values = parse_filters(filters)
	metric = values.pop("metric", "today_sales")
	if metric not in CARD_METRICS:
		frappe.throw(_("Unknown dashboard metric."))
	_name, _label, period, measure = CARD_METRICS[metric]
	today = getdate()
	start = today - timedelta(days=1) if period == "today" else getdate(add_months(today.replace(day=1), -1))
	ctx = Context(REPORTS["daily_sales"], {**values, "from_date": str(start), "to_date": str(today)})
	business_days = {store: get_business_date(store) for store in ctx.stores}
	facts = [
		r
		for r in invoice_facts(ctx)
		if not r.get("is_return")
		and (
			getdate(r["business_date"]) == business_days[r["store"]]
			if period == "today"
			else getdate(r["business_date"]).replace(day=1) == business_days[r["store"]].replace(day=1)
		)
	]
	count = len({r["invoice"] for r in facts})
	sales = sum(r["collected"] for r in facts)
	value = (
		count
		if measure == "invoices"
		else sales / count
		if measure == "average" and count
		else sales
		if measure == "sales"
		else 0
	)
	return dict(
		value=value,
		fieldtype="Int" if measure == "invoices" else "Currency",
		options="currency",
		currency=ctx.currency,
		rms_analytics=1,
		route=["query-report", REPORTS["daily_sales"]["name"]],
		route_options=dict(
			**{
				key: values[key]
				for key in ("store", "brand", "order_type", "product", "category", "customer", "cashier")
				if values.get(key)
			},
			company=ctx.company,
			from_date=str(
				min(business_days.values(), default=today)
				if period == "today"
				else min((d.replace(day=1) for d in business_days.values()), default=today.replace(day=1))
			),
			to_date=str(today),
			business_period=period,
			include_returns=0,
		),
	)


@frappe.whitelist()
def get_chart(chart_name=None, chart=None, filters=None, from_date=None, to_date=None, **kwargs):
	if chart_name:
		doc = frappe.get_doc("Dashboard Chart", chart_name)
		doc.check_permission("read")
		values = parse_filters(doc.filters_json)
	elif chart:
		parsed = parse_filters(chart)
		values = parse_filters(parsed.get("filters_json"))
	else:
		values = {}
	values.update(parse_filters(filters))
	key = values.pop("report_key", "timeline")
	if key not in REPORTS:
		frappe.throw(_("Unknown RMS report."))
	if from_date:
		values["from_date"] = from_date
	if to_date:
		values["to_date"] = to_date
	result = execute(key, values)
	if result[3]:
		return result[3]["data"]
	from rms.analytics.sales import chart as build_chart

	rows = result[1]
	measure = (
		"revenue"
		if any("revenue" in r for r in rows)
		else "printed"
		if key == "printing"
		else "prep_minutes"
		if key == "kitchen"
		else "balance_value"
	)
	return build_chart(rows, measure)["data"]


@frappe.whitelist()
def get_catalog():
	if frappe.session.user == "Guest":
		frappe.throw(_("Sign in to view this report."), frappe.PermissionError)
	from frappe.boot import get_allowed_report_names

	allowed = get_allowed_report_names()
	rows = frappe.get_all(
		"Report", filters={"disabled": 0}, fields=["name", "module", "ref_doctype", "report_type"]
	)
	by_name = {spec["name"]: spec for spec in REPORTS.values()}
	result = []
	for r in rows:
		if r.name not in allowed or not frappe.has_permission(r.ref_doctype, "report"):
			continue
		spec = by_name.get(r.name)
		result.append(
			dict(
				name=r.name,
				title=_(r.name),
				workspace=spec["workspace"] if spec else r.module,
				family=spec["family"] if spec else "core",
				native=not bool(spec),
				ref_doctype=r.ref_doctype,
				report_type=r.report_type,
			)
		)
	return dict(
		reports=sorted(result, key=lambda r: (r["workspace"], r["title"])),
		business_dashboard="RMS Business Review"
		if any(r["name"] == REPORTS["daily_sales"]["name"] for r in result)
		else None,
		companies=frappe.get_list("Company", fields=["name", "default_currency"], limit_page_length=0),
		default_company=frappe.defaults.get_user_default("Company"),
	)
