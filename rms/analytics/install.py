"""Idempotent analytics metadata installation, preserving existing workspace content."""

import json

import frappe

from rms.analytics.catalog import REPORTS, CARD_METRICS

CHARTS = {
	"RMS Supplier Purchase Leaders": ("purchase_summary", "Bar", "Buying"),
	"RMS Production Completion": ("production", "Bar", "Manufacturing"),
	"RMS Revenue Trend": ("timeline", "Line", "Selling"),
	"RMS Payment Distribution": ("payments", "Bar", "Accounting"),
	"RMS Product Leaders": ("products", "Bar", "Selling"),
	"RMS Category Leaders": ("categories", "Bar", "Selling"),
	"RMS Cashier Leaders": ("cashiers", "Bar", "Management"),
	"RMS Table Leaders": ("tables", "Bar", "Selling"),
	"RMS Order Type Mix": ("order_types", "Bar", "Selling"),
}


def report_link(spec):
	return dict(
		type="Link",
		label=spec["name"],
		link_type="Report",
		link_to=spec["name"],
		is_query_report=1,
		report_ref_doctype=spec["ref_doctype"],
		hidden=0,
		onboard=0,
	)


def merge_workspace(workspace, reports, charts=(), cards=()):
	"""Append RMS-owned blocks only; retain all user/ERP blocks and child rows."""
	content = json.loads(workspace.content or "[]")
	ids = {r.get("id") for r in content}
	changed = False
	links = {(r.link_type, r.link_to) for r in workspace.links if r.type == "Link"}
	new = [spec for spec in reports if ("Report", spec["name"]) not in links]
	need_page = not any(
		r.link_type == "Page" and r.link_to == "rms-insights" for r in workspace.links if r.type == "Link"
	)
	if new or need_page:
		label = "RMS Insights"
		start = next(
			(i for i, r in enumerate(workspace.links) if r.type == "Card Break" and r.label == label), None
		)
		if start is None:
			workspace.append("links", dict(type="Card Break", label=label, hidden=0, link_count=0))
			start = len(workspace.links) - 1
		end = next(
			(i for i in range(start + 1, len(workspace.links)) if workspace.links[i].type == "Card Break"),
			len(workspace.links),
		)
		additions = [report_link(spec) for spec in new]
		if need_page:
			additions.append(
				dict(type="Link", label="Report Explorer", link_type="Page", link_to="rms-insights", hidden=0)
			)
		for addition in additions:
			row = workspace.append("links", addition)
			workspace.links.remove(row)
			workspace.links.insert(end, row)
			end += 1
		workspace.links[start].link_count = end - start - 1
		for i, row in enumerate(workspace.links, 1):
			row.idx = i
		if "rms-analytics-reports" not in ids:
			content.append(dict(id="rms-analytics-reports", type="card", data=dict(card_name=label, col=12)))
			ids.add("rms-analytics-reports")
		changed = True
	for name in charts:
		if any(r.chart_name == name for r in workspace.charts):
			continue
		workspace.append("charts", dict(chart_name=name, label=name))
		block_id = "rms-chart-" + frappe.scrub(name)
		if block_id not in ids:
			content.append(dict(id=block_id, type="chart", data=dict(chart_name=name, col=6)))
			ids.add(block_id)
		changed = True
	for name in cards:
		if any(r.number_card_name == name for r in workspace.number_cards):
			continue
		workspace.append("number_cards", dict(number_card_name=name, label=name))
		block_id = "rms-number-" + frappe.scrub(name)
		if block_id not in ids:
			content.insert(0, dict(id=block_id, type="number_card", data=dict(number_card_name=name, col=4)))
			ids.add(block_id)
		changed = True
	if changed:
		workspace.content = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
		workspace.save(ignore_permissions=True)
	return changed


def ensure_analytics():
	"""No transaction, role permission, user assignment or ERP source-file changes."""
	developer_mode = frappe.conf.developer_mode
	frappe.conf.developer_mode = 0
	try:
		for spec in REPORTS.values():
			if frappe.db.exists("Report", spec["name"]):
				existing = frappe.db.get_value(
					"Report", spec["name"], ["module", "is_standard"], as_dict=True
				)
				if existing.module != "RMS" or existing.is_standard != "Yes":
					raise ValueError("An existing custom report owns this name: " + spec["name"])
			frappe.reload_doc("rms", "report", frappe.scrub(spec["name"]), force=True)
		frappe.reload_doc("rms", "page", "rms_insights", force=True)
		frappe.reload_doc("rms", "dashboard_chart_source", "rms_analytics", force=True)
		for name in CHARTS:
			frappe.reload_doc("rms", "dashboard_chart", frappe.scrub(name), force=True)
		for definition in CARD_METRICS.values():
			frappe.reload_doc("rms", "number_card", frappe.scrub(definition[0]), force=True)
		frappe.reload_doc("rms", "dashboard", "rms_business_review", force=True)
		for name in ["Management", "Selling", "Accounting", "Stock", "Buying", "Manufacturing", "CRM"]:
			if not frappe.db.exists("Workspace", name):
				continue
			workspace = frappe.get_doc("Workspace", name, for_update=True)
			reports = [r for r in REPORTS.values() if r["workspace"] == name]
			if name == "Management":
				reports = [
					REPORTS[k]
					for k in ["business_day", "stores", "kitchen", "printing", "daily_sales", "margin"]
				]
			charts = [n for n, d in CHARTS.items() if d[2] == name]
			if name == "Management":
				charts = ["RMS Revenue Trend", "RMS Payment Distribution"]
			cards = (
				[d[0] for k, d in CARD_METRICS.items() if k.startswith("today_")]
				if name in {"Management", "Selling"}
				else []
			)
			merge_workspace(workspace, reports, charts, cards)
			if name == "Management" and not any(
				row.type == "Dashboard" and row.link_to == "RMS Business Review"
				for row in workspace.shortcuts
			):
				workspace.append(
					"shortcuts",
					dict(
						type="Dashboard",
						link_to="RMS Business Review",
						label="Business Dashboard",
						icon="chart",
						color="#24785e",
					),
				)
				content = json.loads(workspace.content or "[]")
				if not any(block.get("id") == "rms-business-dashboard" for block in content):
					content.append(
						dict(
							id="rms-business-dashboard",
							type="shortcut",
							data=dict(shortcut_name="Business Dashboard", col=4),
						)
					)
				workspace.content = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
				workspace.save(ignore_permissions=True)
		# Expose the permission-filtered explorer from other existing workspaces too.
		for name in frappe.get_all("Workspace", filters={"public": 1, "is_hidden": 0}, pluck="name"):
			if name in {"Management", "Selling", "Accounting", "Stock", "Buying", "Manufacturing", "CRM"}:
				continue
			workspace = frappe.get_doc("Workspace", name, for_update=True)
			merge_workspace(workspace, [])
		frappe.clear_cache()
	finally:
		frappe.conf.developer_mode = developer_mode
