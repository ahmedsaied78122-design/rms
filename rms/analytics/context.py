"""Shared validation and permission scope for reports and dashboard requests."""

from datetime import datetime, time, timedelta
import json

import frappe
from frappe import _
from frappe.utils import cint, date_diff, getdate

from rms.analytics.catalog import GROUPS, INVENTORY_FAMILIES, ENTERPRISE_FAMILIES

MAX_ROWS = 50000


def names(value):
	if value in (None, "", []):
		return []
	if isinstance(value, str):
		if value.startswith("["):
			try:
				value = json.loads(value)
			except ValueError:
				frappe.throw(_("Choose valid report filter values."))
		else:
			value = [value]
	if not isinstance(value, (list, tuple)) or any(not isinstance(x, str) for x in value):
		frappe.throw(_("Choose valid report filter values."))
	return list(dict.fromkeys(x for x in value if x))


def limited(rows):
	if len(rows) > MAX_ROWS:
		frappe.throw(_("This report contains too many records. Narrow the dates or filters."))
	return rows


class Context:
	def __init__(self, spec, filters=None):
		self.spec = spec
		self.filters = frappe._dict(filters or {})
		self.user = frappe.session.user
		if self.user == "Guest":
			frappe.throw(_("Sign in to view this report."), frappe.PermissionError)
		self.roles = set(frappe.get_roles())
		allowed_roles = (
			{
				"System Manager",
				"Stock Manager",
				"Purchase Manager",
				"Accounts Manager",
				"Sales Manager",
				"Manufacturing User",
			}
			if spec["family"] in INVENTORY_FAMILIES or spec["family"] in ENTERPRISE_FAMILIES
			else {"System Manager", "POS Manager", "Sales Manager", "Accounts Manager"}
		)
		if not self.roles.intersection(allowed_roles) or not frappe.has_permission(
			spec["ref_doctype"], "report"
		):
			frappe.throw(_("You do not have permission to view this report."), frappe.PermissionError)
		self.company = self.filters.company or frappe.defaults.get_user_default("Company")
		if not self.company:
			available = frappe.get_list("Company", pluck="name", limit_page_length=2)
			if len(available) == 1:
				self.company = available[0]
		if not self.company:
			frappe.throw(_("Choose a Company before running this report."))
		if not frappe.has_permission("Company", doc=self.company):
			frappe.throw(_("This Company is not available to you."), frappe.PermissionError)
		self.currency = frappe.get_cached_value("Company", self.company, "default_currency")
		self.from_date = getdate(self.filters.from_date or getdate().replace(day=1))
		self.to_date = getdate(self.filters.to_date or getdate())
		if self.from_date > self.to_date:
			frappe.throw(_("Start Date must be on or before End Date."))
		if date_diff(self.to_date, self.from_date) >= 366:
			frappe.throw(_("Choose a date range of one year or less."))
		self.start = datetime.combine(self.from_date, time.min)
		self.end = datetime.combine(self.to_date + timedelta(days=1), time.min)
		self.compare = bool(cint(self.filters.compare_previous))
		self.group = self.filters.group_by or spec["group_by"]
		if (
			spec["family"]
			in {"sales", "discounts", "rounding", "margin", "margin_change", "engineering", "price_impact"}
			and self.group not in GROUPS
		):
			frappe.throw(_("Choose a supported report grouping."))
		erp_scope = spec["family"] in ENTERPRISE_FAMILIES or spec["family"] in INVENTORY_FAMILIES - {
			"availability"
		}
		self.stores = [] if erp_scope else self.allowed_stores()
		from rms.api.pos import get_pos_user_scope_values

		self.scopes = (
			{} if erp_scope else {key: get_pos_user_scope_values(key) for key in ("brand", "order_type")}
		)
		if spec["family"] == "kitchen":
			self.scopes["preparation_area"] = get_pos_user_scope_values("preparation_area")
		for scope_name, permitted in self.scopes.items():
			selected = names(self.filters.get(scope_name))
			if permitted and selected and not set(selected) <= set(permitted):
				frappe.throw(
					_("One or more report filters are outside your POS User scope."), frappe.PermissionError
				)
		self.categories = self.category_scope()
		self.warehouses = None

	def allowed_stores(self):
		rows = frappe.get_all("Store", filters={"company": self.company}, fields=["name"])
		all_names = {r.name for r in rows}
		pos_user = frappe.db.get_value("POS User", {"user": self.user}, ["name", "enabled"], as_dict=True)
		if pos_user and not pos_user.enabled:
			frappe.throw(_("Your POS User account is disabled."), frappe.PermissionError)
		if pos_user:
			assigned = set(
				frappe.get_all(
					"POS User Store",
					filters={"parent": pos_user.name, "parenttype": "POS User"},
					pluck="store",
				)
			)
			all_names &= assigned
		elif "System Manager" not in self.roles:
			assignments = frappe.get_all(
				"Store User Assignment",
				filters={"enabled": 1, "parenttype": "Store"},
				fields=["parent", "user"],
			)
			restricted = {r.parent for r in assignments}
			allowed = {r.parent for r in assignments if r.user == self.user}
			all_names -= restricted - allowed
		requested = names(self.filters.store)
		if requested and not set(requested) <= all_names:
			frappe.throw(_("One or more selected Stores are not available to you."), frappe.PermissionError)
		return sorted(set(requested) if requested else all_names)

	def category_scope(self):
		requested = names(self.filters.category)
		if not requested:
			return []
		found = set()
		for category in requested:
			bounds = frappe.db.get_value("Product Category", category, ["lft", "rgt"], as_dict=True)
			if not bounds:
				frappe.throw(_("Choose an existing Product Category."))
			found.update(
				frappe.get_all(
					"Product Category",
					filters={"lft": [">=", bounds.lft], "rgt": ["<=", bounds.rgt]},
					pluck="name",
				)
			)
		return sorted(found)

	def warehouse_scope(self):
		if self.warehouses is not None:
			return self.warehouses
		rows = frappe.get_list(
			"Warehouse",
			filters={"company": self.company, "is_group": 0},
			fields=["name"],
			limit_page_length=0,
		)
		available = {r.name for r in rows}
		requested = names(self.filters.warehouse)
		if requested:
			expanded = set()
			for warehouse in requested:
				bounds = frappe.db.get_value("Warehouse", warehouse, ["company", "lft", "rgt"], as_dict=True)
				if not bounds or bounds.company != self.company:
					frappe.throw(_("Choose a Warehouse in the selected Company."))
				expanded.update(
					frappe.get_list(
						"Warehouse",
						filters={
							"lft": [">=", bounds.lft],
							"rgt": ["<=", bounds.rgt],
							"is_group": 0,
							"company": self.company,
						},
						pluck="name",
						limit_page_length=0,
					)
				)
			available &= expanded
		self.warehouses = sorted(available)
		return self.warehouses

	def previous_filters(self):
		days = date_diff(self.to_date, self.from_date) + 1
		return {
			**self.filters,
			"from_date": str(self.from_date - timedelta(days=days)),
			"to_date": str(self.from_date - timedelta(days=1)),
			"compare_previous": 0,
		}

	def query(self, sql, values=None):
		return self.guard(
			limited(
				frappe.db.sql(
					sql.rstrip().rstrip(";") + f" LIMIT {MAX_ROWS + 1}",
					{
						"company": self.company,
						"stores": self.stores or [""],
						"from_date": self.from_date,
						"to_date": self.to_date,
						"start": self.start,
						"end": self.end,
						**(values or {}),
					},
					as_dict=True,
				)
			)
		)

	def guard(self, rows):
		if not rows:
			return rows
		from frappe.desk.query_report import get_filtered_data

		links = {
			"store": "Store",
			"brand": "Restaurant Brand",
			"order_type": "Order Type",
			"product": "Selling Product",
			"category": "Product Category",
			"customer": "Customer",
			"cashier": "User",
			"warehouse": "Warehouse",
			"item": "Item",
			"item_code": "Item",
			"supplier": "Supplier",
			"mode_of_payment": "Mode of Payment",
			"expense": "Shift Expense",
			"invoice": "POS Invoice",
			"sales_invoice": "Sales Invoice",
			"purchase_invoice": "Purchase Invoice",
			"stock_entry": "Stock Entry",
			"work_order": "Work Order",
			"job_card": "Job Card",
			"inspection": "Quality Inspection",
			"account": "Account",
			"cost_center": "Cost Center",
			"preparation_area": "Preparation Area",
			"print_device": "Print Device",
			"workstation": "Workstation",
			"operation": "Operation",
			"inspected_by": "User",
			"order_name": "POS Order",
			"dining_area": "Dining Area",
			"dining_table": "Dining Table",
		}
		present = set().union(*(set(r) for r in rows))
		columns = [
			{"fieldname": key, "fieldtype": "Link", "options": dt}
			for key, dt in links.items()
			if key in present
		]
		return get_filtered_data(self.spec["ref_doctype"], columns, rows, self.user)

	def accepts(self, row):
		for key, permitted in self.scopes.items():
			if permitted and row.get(key) not in permitted:
				return False
		for filter_name, data_name in [
			("brand", "brand"),
			("order_type", "order_type"),
			("product", "product"),
			("customer", "customer"),
			("cashier", "cashier"),
			("dining_area", "dining_area"),
			("dining_table", "dining_table"),
		]:
			selected = names(self.filters.get(filter_name))
			if selected and row.get(data_name) not in selected:
				return False
		return not self.categories or row.get("category") in self.categories
