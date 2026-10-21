import hashlib
import hmac
import json
from html import escape as html_escape
import re
import secrets
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import flt, now_datetime, nowdate

from rms.stock import create_material_issue
from rms.snapshots import parse_json_rows, serialize_json_rows
from rms.rms.doctype.pos_order.pos_order import get_active_order_item_qty, validate_confirmed_item_cancellation
from rms.taxes import (
	allow_rms_cashier_session_pos_invoice,
	apply_order_discount as _apply_order_discount,
	apply_order_tax_template as _apply_order_tax_template,
	prevent_pos_item_price_autoinsert,
)
POS_ROLES = {"POS Cashier", "POS Manager", "System Manager"}
KITCHEN_MUTATION_ROLES = {"Kitchen Operator", "POS Manager", "System Manager"}
KITCHEN_CANCELLATION_ACKNOWLEDGEMENT = "Acknowledge Cancellation"
POS_DISCOUNT_APPROVAL_ACTION = "POS Order Discount"
POS_CAPABILITIES = (
	"can_view_tables", "can_view_open_orders", "can_view_sales_history", "can_reprint_receipts",
	"can_checkout", "can_edit_open_orders", "can_apply_manual_discount", "can_cancel_orders", "can_transfer_tables",
	"can_split_orders", "can_merge_orders", "can_request_returns", "can_access_kitchen",
	"can_prepare_orders", "can_pick_orders", "can_acknowledge_cancellations",
)
POS_USER_SCOPES = {
	"brand": ("POS User Brand", "restaurant_brand", "allowed_brands"),
	"order_type": ("POS User Order Type", "order_type", "allowed_order_types"),
	"preparation_area": ("POS User Preparation Area", "preparation_area", "allowed_preparation_areas"),
}


def get_pos_return_permission_query(user=None):
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if user == "Administrator" or "System Manager" in roles:
		return ""
	if "POS Manager" in roles:
		pos_user = frappe.db.get_value("POS User", {"user": user, "enabled": 1}, "name")
		if pos_user:
			user_sql = frappe.db.escape(user)
			return f"`tabPOS Return`.store in (select pus.store from `tabPOS User Store` pus inner join `tabPOS User` pu on pu.name = pus.parent where pus.parenttype = 'POS User' and pu.user = {user_sql} and pu.enabled = 1)"
		user_sql = frappe.db.escape(user)
		return f"(`tabPOS Return`.store in (select sua.parent from `tabStore User Assignment` sua where sua.user = {user_sql} and sua.enabled = 1) or not exists (select 1 from `tabStore User Assignment` sua2 where sua2.parent = `tabPOS Return`.store and sua2.enabled = 1))"
	if "POS Cashier" in roles:
		return f"`tabPOS Return`.owner = {frappe.db.escape(user)}"
	return "1 = 0"


def has_pos_return_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if user == "Administrator" or "System Manager" in roles:
		return True
	if permission_type == "read" and doc.owner == user:
		return True
	if "POS Manager" in roles and permission_type in ("read", "write"):
		return _user_has_store_access(user, doc.store)
	return False


def get_shift_expense_permission_query(user=None):
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if user == "Administrator" or "System Manager" in roles:
		return ""
	if "POS Manager" in roles:
		pos_user = frappe.db.get_value("POS User", {"user": user, "enabled": 1}, "name")
		if pos_user:
			user_sql = frappe.db.escape(user)
			return f"`tabShift Expense`.store in (select pus.store from `tabPOS User Store` pus inner join `tabPOS User` pu on pu.name = pus.parent where pus.parenttype = 'POS User' and pu.user = {user_sql} and pu.enabled = 1)"
		if frappe.db.exists("POS User", {"user": user}):
			return "1 = 0"
		user_sql = frappe.db.escape(user)
		return f"(`tabShift Expense`.store in (select sua.parent from `tabStore User Assignment` sua where sua.user = {user_sql} and sua.enabled = 1) or not exists (select 1 from `tabStore User Assignment` sua2 where sua2.parent = `tabShift Expense`.store and sua2.enabled = 1))"
	if "POS Cashier" in roles:
		return f"`tabShift Expense`.owner = {frappe.db.escape(user)}"
	return "1 = 0"


def get_approval_challenge_permission_query(user=None):
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if user == "Administrator" or "System Manager" in roles:
		return ""
	if "POS Manager" not in roles:
		return "1 = 0"
	pos_user = frappe.db.get_value("POS User", {"user": user, "enabled": 1}, "name")
	if pos_user:
		user_sql = frappe.db.escape(user)
		return f"`tabApproval Challenge`.store in (select pus.store from `tabPOS User Store` pus inner join `tabPOS User` pu on pu.name = pus.parent where pus.parenttype = 'POS User' and pu.user = {user_sql} and pu.enabled = 1)"
	if frappe.db.exists("POS User", {"user": user}):
		return "1 = 0"
	user_sql = frappe.db.escape(user)
	return f"(`tabApproval Challenge`.store in (select sua.parent from `tabStore User Assignment` sua where sua.user = {user_sql} and sua.enabled = 1) or not exists (select 1 from `tabStore User Assignment` sua2 where sua2.parent = `tabApproval Challenge`.store and sua2.enabled = 1))"


def has_shift_expense_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if user == "Administrator" or "System Manager" in roles:
		return True
	if "POS Manager" in roles and permission_type in ("read", "write"):
		return _user_has_store_access(user, doc.store)
	return bool(permission_type == "read" and "POS Cashier" in roles and doc.owner == user)


def has_approval_challenge_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if user == "Administrator" or "System Manager" in roles:
		return True
	return bool("POS Manager" in roles and permission_type == "read" and _user_has_store_access(user, doc.store))


def _user_has_store_access(user, store):
	pos_user = frappe.db.get_value("POS User", {"user": user, "enabled": 1}, "name")
	if pos_user:
		return bool(frappe.db.exists("POS User Store", {
			"parent": pos_user, "parenttype": "POS User", "store": store,
		}))
	if frappe.db.exists("POS User", {"user": user}):
		return False
	assigned = frappe.get_all("Store User Assignment", filters={
		"parent": store, "parenttype": "Store", "enabled": 1,
	}, pluck="user")
	return not assigned or user in assigned


def require_pos_role():
	if frappe.session.user == "Guest" or not (set(frappe.get_roles(frappe.session.user)) & POS_ROLES):
		frappe.throw(_("You do not have a POS role."), frappe.PermissionError)


def get_pos_capabilities(user=None):
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	can_approve_discount = bool(roles & {"POS Manager", "System Manager"})
	pos_user = get_active_pos_user(user)
	if not pos_user:
		return {**{fieldname: True for fieldname in POS_CAPABILITIES}, "can_approve_discount": can_approve_discount}
	values = frappe.db.get_value("POS User", pos_user, list(POS_CAPABILITIES), as_dict=True) or {}
	return {**{fieldname: bool(1 if values.get(fieldname) is None else values.get(fieldname)) for fieldname in POS_CAPABILITIES},
		"can_approve_discount": can_approve_discount}


@frappe.whitelist()
def get_pos_user_role_summary(user):
	"""Return the effective roles shown on POS User forms to authorized managers."""
	if not frappe.has_permission("POS User", "read"):
		frappe.throw(_("You are not permitted to read POS User records."), frappe.PermissionError)
	if not frappe.db.get_value("User", {"name": user, "enabled": 1}, "name"):
		frappe.throw(_("Select an enabled Frappe User."))
	return ", ".join(sorted(set(frappe.get_roles(user))))


def require_pos_capability(fieldname):
	if fieldname not in POS_CAPABILITIES:
		frappe.throw(_("Unknown POS permission."), frappe.PermissionError)
	if not get_pos_capabilities().get(fieldname, False):
		frappe.throw(_("Your POS User permissions do not allow this action."), frappe.PermissionError)


def require_pos_action(fieldname):
	require_pos_role()
	require_pos_capability(fieldname)


def get_pos_user_scope_values(scope, user=None):
	"""Return a selected per-user allowlist, or None when that scope is unrestricted."""
	if scope not in POS_USER_SCOPES:
		frappe.throw(_("Unknown POS data scope."), frappe.PermissionError)
	user = user or frappe.session.user
	pos_user = get_active_pos_user(user)
	if not pos_user:
		return None
	doctype, link_field, table_field = POS_USER_SCOPES[scope]
	values = set(frappe.get_all(doctype, filters={
		"parent": pos_user, "parenttype": "POS User", "parentfield": table_field,
	}, pluck=link_field))
	return values or None


def is_pos_scope_allowed(scope, value, user=None):
	allowed = get_pos_user_scope_values(scope, user)
	return allowed is None or value in allowed


def require_pos_scope(scope, value):
	if value and not is_pos_scope_allowed(scope, value):
		frappe.throw(_("Your POS User permissions do not allow this {0}.").format(scope.replace("_", " ")), frappe.PermissionError)


def require_order_scope(order):
	require_pos_scope("brand", order.restaurant_brand)
	require_pos_scope("order_type", order.order_type)


def require_kitchen_role():
	if frappe.session.user == "Guest" or not (set(frappe.get_roles(frappe.session.user)) & (POS_ROLES | {"Kitchen Operator"})):
		frappe.throw(_("You do not have permission to access the Kitchen Display."), frappe.PermissionError)


def require_kitchen_capability(fieldname):
	require_kitchen_role()
	require_pos_capability(fieldname)


def can_manage_kitchen_tickets(user=None):
	return bool(set(frappe.get_roles(user or frappe.session.user)) & KITCHEN_MUTATION_ROLES)


def get_active_pos_user(user):
	pos_user = frappe.db.get_value("POS User", {"user": user, "enabled": 1}, "name")
	if not pos_user and frappe.db.exists("POS User", {"user": user}):
		frappe.throw(_("Your POS User account is disabled."), frappe.PermissionError)
	return pos_user


def get_pos_profile_for_store(store, user=None):
	"""Resolve the cashier's assigned till profile, falling back to the Store default."""
	user = user or frappe.session.user
	pos_user = get_active_pos_user(user)
	if pos_user:
		profile = frappe.db.get_value("POS User Store", {
			"parent": pos_user, "parenttype": "POS User", "store": store,
		}, "pos_profile")
		if profile:
			return profile
	return frappe.db.get_value("Store", store, "pos_profile")


def get_profile_for_new_session(store, user):
	"""Return an unused cashier profile, cloning the Store profile for POS Users when needed."""
	profile_name = get_pos_profile_for_store(store.name, user)
	if not profile_name:
		return None
	opening = frappe.db.get_value("POS Opening Entry", {
		"pos_profile": profile_name, "status": "Open", "docstatus": 1,
	}, ["name", "user"], as_dict=True)
	if not opening or opening.user == user:
		return profile_name

	pos_user = get_active_pos_user(user)
	if not pos_user:
		cashier = frappe.db.get_value("User", opening.user, "full_name") or opening.user
		frappe.throw(_("{0} is already open for {1}. Assign this cashier a separate POS Profile in POS User → Assigned Stores to open another session.").format(profile_name, cashier))

	base_profile = frappe.get_doc("POS Profile", profile_name)
	full_name = frappe.db.get_value("User", user, "full_name") or user.split("@", 1)[0]
	profile_slug = re.sub(r"[^a-z0-9]+", "-", f"{store.name}-{full_name}".lower()).strip("-")[:110]
	profile_suffix = hashlib.sha256(f"{store.name}|{user}".encode()).hexdigest()[:8]
	profile_copy_name = f"RMS-{profile_slug}-{profile_suffix}"
	if frappe.db.exists("POS Profile", profile_copy_name):
		profile_copy = frappe.get_doc("POS Profile", profile_copy_name)
		if profile_copy.company != store.company or profile_copy.disabled:
			frappe.throw(_("An automatically assigned cashier POS Profile is disabled or belongs to another Company."))
	else:
		profile_copy = frappe.copy_doc(base_profile)
		profile_copy.name = profile_copy_name
		profile_copy.disabled = 0
		profile_copy.set("applicable_for_users", [])
		profile_copy.append("applicable_for_users", {"user": user, "default": 1})
		profile_copy.insert(ignore_permissions=True)

	user_doc = frappe.get_doc("POS User", pos_user)
	store_assignment = next((row for row in user_doc.stores if row.store == store.name), None)
	if not store_assignment:
		frappe.throw(_("This POS User is not assigned to the selected Store."), frappe.PermissionError)
	store_assignment.pos_profile = profile_copy.name
	user_doc.save(ignore_permissions=True)
	return profile_copy.name


def create_cashier_session_for_opening(store, profile_name, opening, opening_amounts=None):
	"""Attach an existing ERPNext opening entry to its RMS cashier session."""
	doc = frappe.get_doc({"doctype": "Cashier Session", "user": frappe.session.user,
		"store": store, "pos_profile": profile_name, "pos_opening_entry": opening.name, "payments": []})
	doc.load_store_defaults()
	doc.load_payment_methods()
	amounts = opening_amounts or {
		row.mode_of_payment: row.opening_amount for row in (opening.get("balance_details") or [])
	}
	for row in doc.payments:
		row.opening_amount = flt(amounts.get(row.mode_of_payment, 0))
	doc.insert(ignore_permissions=True)
	return doc


def assert_store_access(store_name):
	store = frappe.db.get_value("Store", store_name, ["name", "enabled", "pos_profile", "company"], as_dict=True)
	if not store or not store.enabled:
		frappe.throw(_("Choose an enabled Store."))
	pos_user = get_active_pos_user(frappe.session.user)
	if pos_user:
		if not frappe.db.exists("POS User Store", {
			"parent": pos_user, "parenttype": "POS User", "store": store_name,
		}):
			frappe.throw(_("You are not assigned to this Store as a POS User."), frappe.PermissionError)
		return store
	allowed = frappe.get_all(
		"Store User Assignment",
		filters={"parent": store_name, "parenttype": "Store", "enabled": 1},
		pluck="user",
	)
	if allowed and frappe.session.user not in allowed:
		frappe.throw(_("You are not allowed to work at this Store."), frappe.PermissionError)
	return store


def get_user_session(store_name=None):
	filters = {"user": frappe.session.user, "status": ["in", ["Open", "Closing"]]}
	if store_name:
		filters["store"] = store_name
	name = frappe.db.get_value("Cashier Session", filters, "name")
	return frappe.get_doc("Cashier Session", name) if name else None


@frappe.whitelist()
def get_expense_context():
	from rms.expenses import get_expense_context as _get_expense_context

	return _get_expense_context()


@frappe.whitelist()
def get_manager_pending_shift_expenses():
	from rms.expenses import get_manager_pending_shift_expenses as _get_manager_pending_shift_expenses

	return _get_manager_pending_shift_expenses()


@frappe.whitelist()
def create_shift_expense(expense_category, amount, mode_of_payment, remarks=None, attachment=None):
	from rms.expenses import create_shift_expense as _create_shift_expense

	return _create_shift_expense(expense_category, amount, mode_of_payment, remarks, attachment)


@frappe.whitelist()
def redeem_shift_expense_approval_code(expense_name, code):
	from rms.expenses import redeem_shift_expense_approval_code as _redeem

	return _redeem(expense_name, code)


@frappe.whitelist()
def issue_shift_expense_approval_code(expense_name):
	from rms.expenses import issue_shift_expense_approval_code as _issue

	return _issue(expense_name)


@frappe.whitelist()
def reject_shift_expense(expense_name, reason):
	from rms.expenses import reject_shift_expense as _reject

	return _reject(expense_name, reason)


def get_brands(store_name):
	allowed = get_pos_user_scope_values("brand")
	rows = frappe.get_all(
		"Store Brand Assignment",
		filters={"parent": store_name, "parenttype": "Store"},
		fields=["restaurant_brand", "is_default", "sequence_id"],
		order_by="sequence_id asc",
	)
	result = []
	for row in rows:
		if allowed is not None and row.restaurant_brand not in allowed:
			continue
		brand = frappe.db.get_value("Restaurant Brand", row.restaurant_brand, ["title", "enabled"], as_dict=True)
		if brand and brand.enabled:
			result.append({"name": row.restaurant_brand, "title": brand.title, "is_default": bool(row.is_default)})
	return result


def get_order_types(store_name):
	allowed = get_pos_user_scope_values("order_type")
	rows = frappe.get_all(
		"Store Order Type Tax",
		filters={"parent": store_name, "parenttype": "Store"},
		fields=["order_type", "sales_taxes_and_charges_template"],
	)
	result = []
	for row in rows:
		if allowed is not None and row.order_type not in allowed:
			continue
		order_type = frappe.db.get_value(
			"Order Type", row.order_type, ["title", "enabled", "sequence_id", "require_table", "require_external_reference"], as_dict=True
		)
		if order_type and order_type.enabled:
			result.append({"name": row.order_type, "title": order_type.title, "sequence_id": order_type.sequence_id,
				"require_table": bool(order_type.require_table), "require_external_reference": bool(order_type.require_external_reference),
				"tax_template": row.sales_taxes_and_charges_template})
	return sorted(result, key=lambda row: (row["sequence_id"], row["title"]))


def get_menu_category_ids(brand_name):
	order = frappe.new_doc("POS Order")
	order.restaurant_brand = brand_name
	return sorted(order.get_brand_menu_categories())


@frappe.whitelist()
def get_pos_context(store):
	require_pos_role()
	store_doc = assert_store_access(store)
	profile_name = get_pos_profile_for_store(store_doc.name)
	if not profile_name:
		frappe.throw(_("Set a POS Profile on the Store or assign one to this POS User."))
	profile = frappe.get_doc("POS Profile", profile_name)
	return {
		"pos_profile": profile.name,
		"customer": profile.customer,
		"selling_price_list": profile.selling_price_list,
		"payments": [{"mode_of_payment": row.mode_of_payment, "default": row.default,
			"type": frappe.db.get_value("Mode of Payment", row.mode_of_payment, "type")}
			for row in profile.payments],
		"manual_discount_scope": store_doc.manual_discount_scope or "Net Total",
		"company": profile.company,
		"currency": frappe.db.get_value("Company", profile.company, "default_currency"),
	}


@frappe.whitelist()
def get_categories(brand, store=None):
	require_pos_role()
	require_pos_scope("brand", brand)
	if store:
		assert_store_access(store)
		if brand not in {row["name"] for row in get_brands(store)}:
			frappe.throw(_("Choose a Brand assigned to this Store."), frappe.PermissionError)
	ids = get_menu_category_ids(brand)
	if not ids:
		return []
	rows = frappe.get_all("Product Category", filters={"name": ["in", ids]},
		fields=["name", "title", "parent_product_category", "sequence_id", "is_group", "image"],
		order_by="sequence_id asc, title asc")
	return rows


@frappe.whitelist()
def get_bootstrap(store=None):
	require_pos_role()
	permissions = get_pos_capabilities()
	store_rows = frappe.get_all("Store", filters={"enabled": 1}, fields=["name", "title", "store_code"])
	allowed_stores = []
	for row in store_rows:
		try:
			assert_store_access(row.name)
			allowed_stores.append(row)
		except frappe.PermissionError:
			continue
	default_store = get_default_pos_store(allowed_stores)

	if store:
		assert_store_access(store)
		store_row = frappe.db.get_value("Store", store, ["name", "title", "store_code", "pos_profile", "operating_day_end"], as_dict=True)
		session = get_user_session(store)
		return {
			"stores": allowed_stores,
			"default_store": default_store,
			"store": store_row,
			"brands": get_brands(store),
			"order_types": get_order_types(store),
			"session": serialize_session(session) if session else None,
			"currency": frappe.db.get_value("Company", frappe.db.get_value("Store", store, "company"), "default_currency"),
			"permissions": permissions,
		}
	session = get_user_session()
	return {"stores": allowed_stores, "default_store": default_store,
		"session": serialize_session(session) if session else None, "permissions": permissions}


def serialize_session(session):
	"""Include a staff display name in the POS bootstrap payload."""
	data = session.as_dict()
	data["user_full_name"] = frappe.db.get_value("User", session.user, "full_name") or session.user
	return data


def get_default_pos_store(allowed_stores, user=None):
	"""Choose the assigned default Store, falling back to the first permitted Store."""
	if not allowed_stores:
		return None
	user = user or frappe.session.user
	pos_user = get_active_pos_user(user)
	if pos_user:
		preferred = frappe.db.get_value("POS User Store", {
			"parent": pos_user, "parenttype": "POS User", "default_store": 1,
		}, "store")
		allowed_names = {row.name for row in allowed_stores}
		if preferred in allowed_names:
			return preferred
	return allowed_stores[0].name


@frappe.whitelist()
def get_catalog(store, brand, order_type, category=None, search=None, limit=100):
	require_pos_role()
	assert_store_access(store)
	if brand not in {row["name"] for row in get_brands(store)}:
		frappe.throw(_("Choose a Brand assigned to this Store."))
	if order_type not in {row["name"] for row in get_order_types(store)}:
		frappe.throw(_("Choose an Order Type enabled for this Store."))

	brand_category_ids = get_menu_category_ids(brand)
	category_ids = set(brand_category_ids)
	if category and category not in category_ids:
		frappe.throw(_("Product Category is not available on a Menu for this Brand."))
	if not category_ids:
		return []
	option_parents = frappe.get_all("Selling Product", filters={
		"enabled": 1, "has_options": 1, "product_category": ["in", list(brand_category_ids)],
	}, pluck="name")
	option_products = set(frappe.get_all("Selling Product Option", filters={
		"parent": ["in", option_parents], "parenttype": "Selling Product",
	}, pluck="option_product")) if option_parents else set()
	if category:
		bounds = frappe.db.get_value("Product Category", category, ["lft", "rgt"], as_dict=True)
		if bounds:
			category_ids = set(category_ids) & set(frappe.get_all("Product Category", filters={
				"lft": [">=", bounds.lft], "rgt": ["<=", bounds.rgt], "enabled": 1,
			}, pluck="name"))
		if not category_ids:
			return []
	filters = {"enabled": 1, "product_category": ["in", list(category_ids)]}
	or_filters = None
	barcode_items = set()
	if search:
		search = str(search).strip()[:80]
		barcode_items = set(frappe.get_all("Item Barcode", filters={"barcode": search}, pluck="parent"))
		or_filters = [{"title": ["like", f"%{search}%"]}]
		if barcode_items:
			or_filters.append({"item": ["in", list(barcode_items)]})
	products = frappe.get_all(
		"Selling Product",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "title", "product_category", "image", "uom", "sequence_id", "has_options", "is_modifier", "can_be_sold_separately"],
		order_by="sequence_id asc, title asc",
		limit_page_length=min(max(int(limit), 1), 200),
	)
	result = []
	for product in products:
		# Option products are selected from their parent product's option dialog.
		if product.name in option_products:
			continue
		if product.is_modifier and not product.can_be_sold_separately:
			continue
		doc = frappe.get_doc("Selling Product", product.name)
		availability = [row for row in doc.store_availability if row.store == store]
		if doc.store_availability and not availability:
			continue
		if any(row.store == store and row.order_type == order_type for row in doc.store_order_type_exclusions):
			continue
		price = None
		if not doc.has_options:
			price = doc.resolve_price(store, order_type, brand, strict=False)
		category_title = frappe.db.get_value("Product Category", product.product_category, "title")
		must_be_whole_number = frappe.get_cached_value("UOM", product.uom, "must_be_whole_number") if product.uom else 0
		result.append({**product, "category_title": category_title, "barcode_match": product.item in barcode_items,
			"must_be_whole_number": bool(must_be_whole_number), "price": price["selling_price"] if price else None,
			"price_list": price["price_list"] if price else None})
	return result


@frappe.whitelist()
def get_product_configuration(product, store, brand, order_type):
	require_pos_role()
	assert_store_access(store)
	if brand not in {row["name"] for row in get_brands(store)}:
		frappe.throw(_("Choose a Brand assigned to this Store."))
	if order_type not in {row["name"] for row in get_order_types(store)}:
		frappe.throw(_("Choose an Order Type enabled for this Store."))
	doc = frappe.get_doc("Selling Product", product)
	if not doc.enabled:
		frappe.throw(_("Selling Product is disabled."))
	options = []
	for row in doc.option_products:
		option = frappe.db.get_value("Selling Product", row.option_product, ["title", "enabled", "has_options"], as_dict=True)
		if option and option.enabled:
			price = frappe.get_doc("Selling Product", row.option_product).resolve_price(store, order_type, brand, strict=False)
			options.append({"name": row.option_product, "title": option.title, "sequence_id": row.sequence_id,
				"has_options": bool(option.has_options),
				"price": None if option.has_options else price["selling_price"] if price else None,
				"price_list": price["price_list"] if price else None})

	groups = []
	for row in doc.modifier_groups:
		group = frappe.db.get_value("Modifier Group", row.modifier_group, ["title", "enabled", "allow_collapse", "collapsed_by_default", "allow_multiple_selections"], as_dict=True)
		if not group or not group.enabled:
			continue
		choices = []
		for option in doc.modifier_options:
			if option.modifier_group != row.modifier_group:
				continue
			product_info = frappe.db.get_value("Selling Product", option.modifier_product, ["title", "enabled", "is_modifier"], as_dict=True)
			if product_info and product_info.enabled and product_info.is_modifier:
				choices.append({"name": option.modifier_product, "title": product_info.title, "cost": option.cost,
					"selling_price": option.selling_price or 0, "sequence_id": option.sequence_id})
		groups.append({"name": row.modifier_group, "title": group.title, "allow_collapse": bool(group.allow_collapse),
			"allow_multiple_selections": bool(group.allow_multiple_selections),
			"collapsed_by_default": bool(group.collapsed_by_default), "sequence_id": row.sequence_id,
			"options": sorted(choices, key=lambda option: (option["sequence_id"], option["title"]))})
	product_price = None if doc.has_options else doc.resolve_price(store, order_type, brand, strict=False)
	must_be_whole_number = frappe.get_cached_value("UOM", doc.uom, "must_be_whole_number") if doc.uom else 0
	return {"name": doc.name, "title": doc.title, "uom": doc.uom,
		"must_be_whole_number": bool(must_be_whole_number), "has_options": bool(doc.has_options),
		"price": product_price["selling_price"] if product_price else None,
		"options": sorted(options, key=lambda option: (option["sequence_id"], option["title"])),
		"modifier_groups": sorted(groups, key=lambda group: (group["sequence_id"], group["title"]))}


@frappe.whitelist()
def get_dining_areas(store):
	require_pos_role()
	assert_store_access(store)
	return frappe.get_all("Dining Area", filters={"store": store, "enabled": 1},
		fields=["name", "title", "sequence_id"], order_by="sequence_id asc, title asc")


@frappe.whitelist()
def get_customers(search=None, limit=30):
	require_pos_role()
	filters = {"disabled": 0}
	if search:
		search = str(search).strip()[:80]
		rows = frappe.get_all("Customer", filters=filters, or_filters=[
			{"customer_name": ["like", f"%{search}%"]}, {"name": ["like", f"%{search}%"]}
		], fields=["name", "customer_name"], order_by="customer_name asc", limit_page_length=min(max(int(limit), 1), 50))
	else:
		rows = frappe.get_all("Customer", filters=filters, fields=["name", "customer_name"], order_by="customer_name asc", limit_page_length=min(max(int(limit), 1), 50))
	return rows


@frappe.whitelist()
def get_tables(store, dining_area=None):
	require_pos_action("can_view_tables")
	assert_store_access(store)
	filters = {"store": store, "enabled": 1}
	if dining_area:
		filters["dining_area"] = dining_area
	tables = frappe.get_all("Dining Table", filters=filters, fields=["name", "title", "dining_area", "capacity", "sequence_id"])
	open_orders = frappe.get_all(
		"POS Order",
		filters={"store": store, "status": ["not in", ["Paid", "Cancelled"]], "dining_table": ["is", "set"]},
		fields=["name", "dining_table", "status", "cashier_session", "restaurant_brand", "order_type", "check_label", "grand_total", "modified"],
	)
	session_names = list({row.cashier_session for row in open_orders if row.cashier_session})
	session_cashiers = get_session_cashier_names(session_names)
	by_table = {}
	occupied_tables = {row.dining_table for row in open_orders}
	can_view_orders = get_pos_capabilities().get("can_view_open_orders", True)
	for order in open_orders:
		if can_view_orders and not (is_pos_scope_allowed("brand", order.restaurant_brand)
			and is_pos_scope_allowed("order_type", order.order_type)):
			continue
		by_table.setdefault(order.dining_table, []).append({"order": order.name, "status": order.status,
			"cashier_session": order.cashier_session, "cashier": session_cashiers.get(order.cashier_session),
			"check_label": order.check_label, "order_type": order.order_type,
			"grand_total": order.grand_total, "modified": order.modified})
	area_titles = {row.name: row.title for row in frappe.get_all(
		"Dining Area", filters={"store": store, "enabled": 1}, fields=["name", "title"]
	)}
	for row in tables:
		row["occupied"] = row.name in occupied_tables
		row["open_orders"] = by_table.get(row.name, []) if can_view_orders else []
		row["open_order"] = row["open_orders"][0] if row["open_orders"] else None
		row["dining_area_title"] = area_titles.get(row.dining_area, row.dining_area)
	return sorted(tables, key=lambda row: (row.sequence_id, row.title))


def get_session_cashier_names(session_names):
	if not session_names:
		return {}
	sessions = frappe.get_all("Cashier Session", filters={"name": ["in", session_names]}, fields=["name", "user"])
	user_names = list({row.user for row in sessions if row.user})
	users = {row.name: row.full_name for row in frappe.get_all("User", filters={"name": ["in", user_names]},
		fields=["name", "full_name"])} if user_names else {}
	return {row.name: users.get(row.user) or row.user for row in sessions}


@frappe.whitelist()
def get_kitchen_board(store, preparation_area=None):
	require_kitchen_capability("can_access_kitchen")
	assert_store_access(store)
	area_filters = {"store": store, "enabled": 1, "has_kds": 1}
	areas = frappe.get_all("Preparation Area", filters=area_filters,
		fields=["name", "title", "sequence_id"], order_by="sequence_id asc, title asc", ignore_permissions=True)
	allowed_areas = get_pos_user_scope_values("preparation_area")
	if allowed_areas is not None:
		areas = [row for row in areas if row.name in allowed_areas]
	if preparation_area:
		if preparation_area not in {row.name for row in areas}:
			frappe.throw(_("Choose a KDS Preparation Area in this Store."))
		ticket_filters = {"store": store, "preparation_area": preparation_area,
			"status": ["in", ["Pending", "Started", "Ready", "Cancelled"]],
			"cancellation_acknowledged_at": ["is", "not set"]}
	else:
		ticket_filters = {"store": store, "status": ["in", ["Pending", "Started", "Ready", "Cancelled"]],
			"cancellation_acknowledged_at": ["is", "not set"]}
	tickets = frappe.get_all("Kitchen Ticket", filters=ticket_filters,
		fields=["name", "pos_order", "preparation_area", "status", "sent_at", "started_at", "ready_at",
			"cancellation_acknowledged_at", "is_item_cancellation_notice", "cancellation_reason"],
		order_by="sent_at asc", ignore_permissions=True)
	allowed_area_names = {row.name for row in areas}
	tickets = [ticket for ticket in tickets if ticket.preparation_area in allowed_area_names]
	for ticket in tickets:
		order = frappe.get_doc("POS Order", ticket.pos_order)
		if not is_pos_scope_allowed("brand", order.restaurant_brand) or not is_pos_scope_allowed("order_type", order.order_type):
			continue
		ticket["order_type"] = order.order_type
		ticket["dining_table"] = order.dining_table
		ticket["lines"] = []
		for row in frappe.get_all("Kitchen Ticket Item", filters={"parent": ticket.name, "parenttype": "Kitchen Ticket"},
			fields=["selling_product", "qty", "cancelled_qty", "modifier_summary", "notes", "status"], order_by="idx asc", ignore_permissions=True):
			row["title"] = frappe.db.get_value("Selling Product", row.selling_product, "title")
			row["remaining_qty"] = get_active_order_item_qty(row.qty, row.cancelled_qty)
			ticket["lines"].append(row)
	permissions = get_pos_capabilities()
	can_manage_tickets = can_manage_kitchen_tickets()
	return {"areas": areas, "tickets": tickets, "permissions": {
		"can_prepare_orders": can_manage_tickets and permissions["can_prepare_orders"],
		"can_pick_orders": can_manage_tickets and permissions["can_pick_orders"],
		"can_acknowledge_cancellations": can_manage_tickets and permissions["can_acknowledge_cancellations"],
	}}


@frappe.whitelist()
def get_kitchen_stores():
	require_kitchen_capability("can_access_kitchen")
	result = []
	for row in frappe.get_all("Store", filters={"enabled": 1}, fields=["name", "title"], ignore_permissions=True):
		try:
			assert_store_access(row.name)
			if frappe.get_all("Preparation Area", filters={"store": row.name, "enabled": 1, "has_kds": 1}, pluck="name"):
				allowed = get_pos_user_scope_values("preparation_area")
				areas = frappe.get_all("Preparation Area", filters={"store": row.name, "enabled": 1, "has_kds": 1}, pluck="name")
				if allowed is not None and not (allowed & set(areas)):
					continue
				result.append(row)
		except frappe.PermissionError:
			continue
	return result


@frappe.whitelist()
def set_kitchen_ticket_status(ticket_name, status):
	require_kitchen_role()
	if not can_manage_kitchen_tickets():
		frappe.throw(_("Kitchen ticket changes require Kitchen Operator or POS Manager role."), frappe.PermissionError)
	if status == KITCHEN_CANCELLATION_ACKNOWLEDGEMENT:
		require_pos_capability("can_acknowledge_cancellations")
	elif status == "Picked":
		require_pos_capability("can_pick_orders")
	else:
		require_pos_capability("can_prepare_orders")
	ticket = frappe.get_doc("Kitchen Ticket", ticket_name)
	assert_store_access(ticket.store)
	require_pos_scope("preparation_area", ticket.preparation_area)
	order = frappe.get_doc("POS Order", ticket.pos_order)
	require_order_scope(order)
	if status == KITCHEN_CANCELLATION_ACKNOWLEDGEMENT:
		if ticket.status != "Cancelled":
			frappe.throw(_("Only cancelled Kitchen Tickets can acknowledge a cancellation."))
		if not ticket.cancellation_acknowledged_at:
			ticket.cancellation_acknowledged_at = now_datetime()
			ticket.cancellation_acknowledged_by = frappe.session.user
			frappe.db.set_value("Kitchen Ticket", ticket.name, {
				"cancellation_acknowledged_at": ticket.cancellation_acknowledged_at,
				"cancellation_acknowledged_by": ticket.cancellation_acknowledged_by,
			})
		return {"name": ticket.name, "status": ticket.status, "acknowledged": True}
	ticket.set_status(status)
	return {"name": ticket.name, "status": ticket.status}


@frappe.whitelist()
def open_session(store, opening_amounts=None):
	require_pos_action("can_checkout")
	store_doc = assert_store_access(store)
	existing_session = get_user_session(store_doc.name)
	if existing_session:
		return {**existing_session.as_dict(), "resumed": True}
	other_session = get_user_session()
	if other_session:
		frappe.throw(_("You already have an open cashier session at {0}. Return to that Store to continue it.").format(other_session.store))
	amounts = frappe.parse_json(opening_amounts or "{}")
	user_openings = frappe.get_all("POS Opening Entry", filters={
		"user": frappe.session.user, "status": "Open", "docstatus": 1,
	}, fields=["name", "pos_profile"], limit_page_length=2)
	profile_name = get_pos_profile_for_store(store_doc.name, frappe.session.user)
	if user_openings:
		opening = next((row for row in user_openings if row.pos_profile == profile_name), None)
		if not opening:
			frappe.throw(_("Your POS Opening Entry {0} is already open on another POS Profile. Return to its Store or ask a manager to reconcile that register before opening another.").format(user_openings[0].name))
		opening_doc = frappe.get_doc("POS Opening Entry", opening.name)
		doc = create_cashier_session_for_opening(store_doc.name, profile_name, opening_doc)
		return {**doc.as_dict(), "resumed": True}
	profile_name = get_profile_for_new_session(store_doc, frappe.session.user)
	if not profile_name:
		frappe.throw(_("Set a POS Profile on the Store or assign one to this POS User."))
	profile = frappe.get_doc("POS Profile", profile_name)
	opening = frappe.get_doc({
		"doctype": "POS Opening Entry",
		"company": profile.company,
		"pos_profile": profile.name,
		"user": frappe.session.user,
		"posting_date": nowdate(),
		"period_start_date": now_datetime(),
		"balance_details": [
			{"mode_of_payment": row.mode_of_payment, "opening_amount": flt(amounts.get(row.mode_of_payment, 0))}
			for row in profile.payments
		],
	})
	opening.insert(ignore_permissions=True)
	opening.submit()
	doc = create_cashier_session_for_opening(store_doc.name, profile.name, opening, amounts)
	return doc.as_dict()


@frappe.whitelist()
def close_session(session_name, actual_amounts=None):
	require_pos_role()
	doc = frappe.get_doc("Cashier Session", session_name)
	assert_store_access(doc.store)
	if doc.user != frappe.session.user:
		frappe.throw(_("This Cashier Session belongs to another User."), frappe.PermissionError)
	actual_amounts = _normalize_actual_amounts(
		actual_amounts,
		[row.mode_of_payment for row in doc.payments],
	)
	if doc.status == "Open":
		doc.begin_closing()
	for row in doc.payments:
		row.actual_amount = actual_amounts[row.mode_of_payment]
	doc.save(ignore_permissions=True)

	if not doc.pos_closing_entry:
		from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import make_closing_entry_from_opening

		opening = frappe.get_doc("POS Opening Entry", doc.pos_opening_entry)
		actor = frappe.session.user
		try:
			frappe.set_user("Administrator")
			closing = make_closing_entry_from_opening(opening)
		finally:
			frappe.set_user(actor)
		closing.posting_date = nowdate()
		for row in doc.payments:
			closing_row = next((item for item in closing.payment_reconciliation if item.mode_of_payment == row.mode_of_payment), None)
			if not closing_row:
				closing_row = closing.append("payment_reconciliation", {"mode_of_payment": row.mode_of_payment})
			closing_row.opening_amount = flt(row.opening_amount)
			closing_row.expected_amount = flt(row.expected_amount)
			closing_row.closing_amount = flt(row.actual_amount)
			closing_row.difference = flt(row.actual_amount) - flt(row.expected_amount)
		closing.insert(ignore_permissions=True)
		doc.pos_closing_entry = closing.name
		doc.save(ignore_permissions=True)
		# Keep a recoverable standard Closing Entry before ERPNext runs invoice consolidation.
		frappe.db.commit()
		closing.flags.ignore_permissions = True
		try:
			actor = frappe.session.user
			try:
				frappe.set_user("Administrator")
				closing.submit()
			finally:
				frappe.set_user(actor)
		except Exception:
			closing.reload()
			if closing.status != "Failed":
				raise
	else:
		closing = frappe.get_doc("POS Closing Entry", doc.pos_closing_entry)
		if closing.status == "Failed":
			try:
				closing.retry()
			except Exception:
				closing.reload()
				if closing.status != "Failed":
					raise
			closing.reload()

	if closing.status == "Submitted" and frappe.db.get_value("POS Opening Entry", doc.pos_opening_entry, "status") == "Closed":
		doc.finish_closing()
	else:
		return {"name": doc.name, "status": "Closing", "pos_closing_entry": closing.name,
			"closing_status": closing.status, "message": _("Invoice consolidation is still processing or needs attention.")}
	return {"name": doc.name, "status": doc.status, "pos_closing_entry": closing.name, "closed_at": doc.closed_at}


def _normalize_actual_amounts(values, payment_methods):
	values = frappe.parse_json(values or "{}")
	if not isinstance(values, dict):
		frappe.throw(_("Enter one actual amount for every payment method configured on this session."))
	methods = list(payment_methods)
	missing = [method for method in methods if method not in values]
	if missing:
		frappe.throw(_("Enter an actual amount for {0}.").format(missing[0]))
	if set(values) != set(methods):
		frappe.throw(_("Only payment methods configured on this session can be counted."))

	amounts = {}
	for method in methods:
		value = values[method]
		if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
			frappe.throw(_("Enter an actual amount for {0}.").format(method))
		try:
			amount = Decimal(str(value))
		except (InvalidOperation, ValueError, TypeError):
			frappe.throw(_("Enter a valid non-negative amount for {0}.").format(method))
		if not amount.is_finite() or amount < 0:
			frappe.throw(_("Enter a valid non-negative amount for {0}.").format(method))
		amounts[method] = flt(amount)
	return amounts


@frappe.whitelist()
def get_open_orders(session_name):
	require_pos_action("can_view_open_orders")
	session = frappe.get_doc("Cashier Session", session_name)
	assert_store_access(session.store)
	if session.user != frappe.session.user:
		frappe.throw(_("This Cashier Session belongs to another User."), frappe.PermissionError)
	orders = frappe.get_all(
		"POS Order",
		filters={"cashier_session": session.name, "status": ["not in", ["Paid", "Cancelled"]]},
		fields=["name", "status", "order_type", "restaurant_brand", "dining_table", "check_label", "business_date", "grand_total", "modified"],
		order_by="modified desc",
	)
	orders = [row for row in orders if is_pos_scope_allowed("brand", row.restaurant_brand)
		and is_pos_scope_allowed("order_type", row.order_type)]
	for row in orders:
		row["item_count"] = frappe.db.count("POS Order Item", {"parent": row.name, "parenttype": "POS Order"})
	return orders


@frappe.whitelist()
def has_open_orders(session_name):
	require_pos_role()
	session = frappe.get_doc("Cashier Session", session_name)
	assert_store_access(session.store)
	if session.user != frappe.session.user:
		frappe.throw(_("This Cashier Session belongs to another User."), frappe.PermissionError)
	return bool(frappe.db.exists("POS Order", {"cashier_session": session.name, "status": ["not in", ["Paid", "Cancelled"]]}))


@frappe.whitelist()
def get_store_open_orders(store):
	"""List active orders at an authorized Store, whether or not the caller has a session."""
	require_pos_action("can_view_open_orders")
	assert_store_access(store)
	orders = frappe.get_all(
		"POS Order",
		filters={"store": store, "status": ["not in", ["Paid", "Cancelled"]]},
		fields=["name", "status", "order_type", "restaurant_brand", "dining_table", "check_label", "business_date", "grand_total", "modified", "cashier_session"],
		order_by="modified desc",
	)
	session_names = list({order.cashier_session for order in orders if order.cashier_session})
	sessions = get_session_cashier_names(session_names)
	orders = [row for row in orders if is_pos_scope_allowed("brand", row.restaurant_brand)
		and is_pos_scope_allowed("order_type", row.order_type)]
	item_counts = {}
	if orders:
		for item in frappe.get_all(
			"POS Order Item",
			filters={"parent": ["in", [row.name for row in orders]], "parenttype": "POS Order"},
			fields=["parent", "sent_to_kitchen", "qty", "cancelled_qty"],
		):
			if get_active_order_item_qty(item.qty, item.cancelled_qty) <= 0:
				continue
			counts = item_counts.setdefault(item.parent, {"total": 0, "sent": 0, "pending": 0})
			counts["total"] += 1
			counts["sent" if item.sent_to_kitchen else "pending"] += 1
	for row in orders:
		row["cashier"] = sessions.get(row.cashier_session)
		counts = item_counts.get(row.name, {"total": 0, "sent": 0, "pending": 0})
		row["item_count"] = counts["total"]
		row["sent_item_count"] = counts["sent"]
		row["pending_item_count"] = counts["pending"]
	return orders


@frappe.whitelist()
def get_open_order_overview(order_name):
	"""Return a read-only summary of an active Store order, independent of cashier session."""
	require_pos_action("can_view_open_orders")
	doc = frappe.get_doc("POS Order", order_name)
	assert_store_access(doc.store)
	require_order_scope(doc)
	if doc.status in ("Paid", "Cancelled"):
		frappe.throw(_("Only active orders can be viewed here."))
	result = {field: doc.get(field) for field in (
		"name", "status", "store", "cashier_session", "restaurant_brand", "order_type", "customer",
		"dining_area", "dining_table", "check_label", "subtotal", "discount_amount", "discount_type", "discount_scope",
		"tax_total", "grand_total", "modified",
	)}
	result["cashier"] = frappe.db.get_value("Cashier Session", doc.cashier_session, "user") if doc.cashier_session else None
	result["items"] = []
	for row in doc.get("items") or []:
		modifiers = [dict(modifier) for modifier in parse_json_rows(row.modifiers)]
		for modifier in modifiers:
			modifier["title"] = frappe.db.get_value("Selling Product", modifier.get("modifier_product"), "title") or modifier.get("modifier_product")
		result["items"].append({
			"title": frappe.db.get_value("Selling Product", row.selling_product, "title") or row.selling_product,
			"qty": get_active_order_item_qty(row.qty, row.cancelled_qty), "ordered_qty": row.qty,
			"cancelled_qty": flt(row.cancelled_qty), "uom": row.uom, "selling_price": row.selling_price,
			"amount": row.amount, "modifiers": modifiers,
		})
	return result


@frappe.whitelist()
def get_open_order_check_print_html(order_name):
	"""Render a confirmed, unpaid check for table-side printing."""
	require_pos_action("can_reprint_receipts")
	order = frappe.get_doc("POS Order", order_name)
	assert_store_access(order.store)
	require_order_scope(order)
	if order.status not in ("Confirmed", "In Preparation", "Ready"):
		frappe.throw(_("Confirm the order before printing its check."))
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	if user != "Administrator" and not ({"System Manager", "POS Manager"} & roles):
		if "POS Cashier" not in roles or not frappe.db.exists("Cashier Session", {
			"name": order.cashier_session, "user": user, "status": ["in", ["Open", "Closing"]]
		}):
			frappe.throw(_("You can only print checks from your own active cashier session."), frappe.PermissionError)

	def esc(value):
		return html_escape(str(value or ""), quote=True)

	rows = []
	for item in order.items:
		title = frappe.db.get_value("Selling Product", item.selling_product, "title") or item.selling_product
		modifier_names = [frappe.db.get_value("Selling Product", row.modifier_product, "title") or row.modifier_product
			for row in parse_json_rows(item.modifiers)]
		details = "".join(f"<small>{esc(label)}</small>" for label in modifier_names)
		if item.notes:
			details += f"<small class=\"note\">{esc(item.notes)}</small>"
		rows.append(f"<tr><td>{esc(title)}{details}</td><td>{flt(item.qty):g}</td><td>{flt(item.amount):,.2f}</td></tr>")
	label = order.check_label or order.name
	return f"""<!doctype html><html><head><meta charset=\"utf-8\"><title>{esc(label)}</title>
	<style>body{{font:14px Arial,sans-serif;color:#172e31;max-width:360px;margin:20px auto}}h1{{font-size:20px;margin:0}}p{{margin:6px 0;color:#546665}}table{{width:100%;border-collapse:collapse;margin-top:18px}}td{{padding:9px 3px;border-bottom:1px solid #dfe5e0;vertical-align:top}}td:nth-child(2),td:nth-child(3){{text-align:right;white-space:nowrap}}small{{display:block;color:#62716c;font-size:11px;margin-top:3px}}.note{{color:#945c19}}.total{{display:flex;justify-content:space-between;margin-top:18px;font-size:18px;font-weight:bold}}@media print{{body{{margin:0 auto}}}}</style></head>
	<body><h1>{esc(label)}</h1><p>{esc(order.dining_table)} · {esc(order.status)}</p><p>{esc(order.store)} · {esc(order.modified)}</p>
	<table><tbody>{''.join(rows)}</tbody></table><div class=\"total\"><span>{esc(_('Total'))}</span><span>{flt(order.grand_total):,.2f}</span></div>
	<script>window.onload=()=>window.print()</script></body></html>"""


def get_pos_sales_history_filters(store, user, roles, session_names):
	filters = {"store": store, "status": "Paid", "pos_invoice": ["is", "set"]}
	if user == "Administrator" or {"System Manager", "POS Manager"} & set(roles):
		return filters
	if "POS Cashier" not in set(roles):
		frappe.throw(_("You are not allowed to view POS sales history."), frappe.PermissionError)
	if not session_names:
		return None
	filters["cashier_session"] = ["in", session_names]
	return filters


@frappe.whitelist()
def get_pos_sales_history(store, limit=50):
	require_pos_action("can_view_sales_history")
	assert_store_access(store)
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	session_names = frappe.get_all("Cashier Session", filters={"store": store, "user": user}, pluck="name")
	filters = get_pos_sales_history_filters(store, user, roles, session_names)
	if filters is None:
		return []
	orders = frappe.get_all("POS Order", filters=filters,
		fields=["name", "pos_invoice", "cashier_session", "order_type", "restaurant_brand", "dining_table", "check_label", "grand_total", "modified"],
		order_by="modified desc", limit_page_length=min(max(int(limit or 50), 1), 100))
	orders = [row for row in orders if is_pos_scope_allowed("brand", row.restaurant_brand)
		and is_pos_scope_allowed("order_type", row.order_type)]
	for order in orders:
		order["cashier"] = frappe.db.get_value("Cashier Session", order.cashier_session, "user")
		order["invoice_status"] = frappe.db.get_value("POS Invoice", order.pos_invoice, "status")
	return orders


@frappe.whitelist()
def get_pos_invoice_print_html(order_name):
	require_pos_action("can_reprint_receipts")
	order = frappe.get_doc("POS Order", order_name)
	assert_store_access(order.store)
	require_order_scope(order)
	if order.status != "Paid" or not order.pos_invoice:
		frappe.throw(_("Only a paid POS sale can be reprinted."))
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	if user != "Administrator" and not ({"System Manager", "POS Manager"} & roles):
		owned_sessions = set(frappe.get_all("Cashier Session", filters={"store": order.store, "user": user}, pluck="name"))
		if "POS Cashier" not in roles or order.cashier_session not in owned_sessions:
			frappe.throw(_("You can only reprint receipts from your own cashier sessions."), frappe.PermissionError)
	invoice = frappe.get_doc("POS Invoice", order.pos_invoice)
	if invoice.docstatus != 1:
		frappe.throw(_("Only a submitted POS Invoice can be reprinted."))
	# The cashier has already passed Store/session authorization above. Render using
	# ERPNext's standard print format because POS Cashier intentionally has no broad
	# read permission on the accounting DocType.
	frappe.set_user("Administrator")
	try:
		return frappe.get_print("POS Invoice", order.pos_invoice, print_format="Standard", no_letterhead=1)
	finally:
		frappe.set_user(user)


@frappe.whitelist()
def get_order(order_name):
	require_pos_role()
	doc = frappe.get_doc("POS Order", order_name)
	assert_store_access(doc.store)
	require_order_scope(doc)
	if doc.cashier_session != frappe.db.get_value("Cashier Session", {"user": frappe.session.user, "status": ["in", ["Open", "Closing"]]}, "name"):
		session = get_user_session(doc.store)
		if not session or session.status != "Open":
			frappe.throw(_("Open your Cashier Session for this Store before editing another cashier’s order."), frappe.PermissionError)
		require_pos_action("can_edit_open_orders")
		if doc.status in ("Paid", "Cancelled"):
			frappe.throw(_("Only active orders can be edited."), frappe.PermissionError)
	result = doc.as_dict()
	for row in result.get("items", []):
		row["title"] = frappe.db.get_value("Selling Product", row.get("selling_product"), "title")
		row["must_be_whole_number"] = bool(frappe.get_cached_value("UOM", row.get("uom"), "must_be_whole_number")) if row.get("uom") else False
		row["modifiers"] = [dict(modifier) for modifier in parse_json_rows(row.get("modifiers"))]
		for modifier in row["modifiers"]:
			modifier["title"] = frappe.db.get_value("Selling Product", modifier.get("modifier_product"), "title")
	return result


def get_owned_order(order_name, allowed_statuses):
	"""Return an order in the caller's active session and Store."""
	require_pos_role()
	doc = frappe.get_doc("POS Order", order_name)
	assert_store_access(doc.store)
	require_order_scope(doc)
	if doc.status not in allowed_statuses:
		frappe.throw(_("This operation is not available for the current order status."))
	if doc.cashier_session != frappe.db.get_value(
		"Cashier Session", {"user": frappe.session.user, "status": "Open", "store": doc.store}, "name"
	):
		frappe.throw(_("This order does not belong to your open Cashier Session."), frappe.PermissionError)
	return doc


def get_owned_draft_order(order_name):
	"""Return an unconfirmed draft belonging to the caller's open session."""
	return get_owned_order(order_name, ("Open", "Pending Confirmation"))


@frappe.whitelist()
def transfer_order(order_name, dining_table):
	"""Move an unpaid table order and notify its kitchen printers."""
	require_pos_action("can_transfer_tables")
	doc = get_owned_order(order_name, ("Open", "Pending Confirmation", "Confirmed", "In Preparation", "Ready"))
	if not dining_table:
		frappe.throw(_("Choose a destination table."))
	order_type = frappe.db.get_value("Order Type", doc.order_type, "require_table")
	if not order_type:
		frappe.throw(_("Table transfer is only available for table orders."))
	table = frappe.db.get_value("Dining Table", dining_table, ["store", "dining_area", "enabled"], as_dict=True)
	if not table or table.store != doc.store or not table.enabled:
		frappe.throw(_("Choose an enabled table in the same Store."))
	if frappe.db.exists("POS Order", {"dining_table": dining_table, "name": ["!=", doc.name], "status": ["not in", ["Paid", "Cancelled"]]}):
		frappe.throw(_("The destination table already has an active order."))
	old_table = doc.dining_table
	doc.dining_table = dining_table
	doc.dining_area = table.dining_area
	doc.flags.allow_table_transfer = True
	doc.save(ignore_permissions=True)
	doc.add_comment("Info", _("Table moved from {0} to {1} by {2}.").format(old_table or _("None"), dining_table, frappe.session.user))
	for area_name in {row.preparation_area for row in frappe.get_all(
		"Kitchen Ticket", filters={"pos_order": doc.name, "status": ["not in", ["Cancelled"]]}, fields=["preparation_area"]
	) if row.preparation_area}:
		area = frappe.get_doc("Preparation Area", area_name)
		if not area.has_printer or not area.print_device:
			continue
		key = frappe.generate_hash(f"TABLE-MOVE|{doc.name}|{old_table}|{dining_table}|{now_datetime()}", length=32)
		frappe.get_doc({
			"doctype": "Print Dispatch Job", "store": doc.store, "preparation_area": area.name,
			"print_device": area.print_device, "document_type": "POS Order", "document_name": doc.name,
			"idempotency_key": key, "status": "Queued",
			"payload": _("TABLE TRANSFERRED\nOrder: {0}\nFrom: {1}\nTo: {2}").format(doc.name, old_table or _("None"), dining_table),
		}).insert(ignore_permissions=True)
	return {"name": doc.name, "dining_table": dining_table, "dining_area": table.dining_area}


@frappe.whitelist()
def merge_orders(target_order, source_order):
	"""Combine two unconfirmed orders from the same cashier session."""
	require_pos_action("can_merge_orders")
	target = get_owned_draft_order(target_order)
	source = get_owned_draft_order(source_order)
	if target.name == source.name:
		frappe.throw(_("Choose two different orders."))
	for fieldname in ("store", "cashier_session", "restaurant_brand", "order_type", "customer", "external_reference"):
		if target.get(fieldname) != source.get(fieldname):
			frappe.throw(_("Orders must share the same {0} to be merged.").format(fieldname.replace("_", " ")))
	if source.dining_table and target.dining_table and source.dining_table != target.dining_table:
		frappe.throw(_("Move one order to the same table before merging."))
	if not target.dining_table and source.dining_table:
		target.dining_table = source.dining_table
		target.dining_area = source.dining_area
	for row in source.items:
		target.append("items", {
			"selling_product": row.selling_product, "option_parent": row.option_parent,
			"qty": row.qty, "notes": row.notes, "modifiers": row.modifiers,
		})
	source.status = "Cancelled"
	source.save(ignore_permissions=True)
	target.save(ignore_permissions=True)
	target.add_comment("Info", _("Order {0} was merged into this order by {1}.").format(source.name, frappe.session.user))
	source.add_comment("Info", _("Merged into order {0} by {1}.").format(target.name, frappe.session.user))
	return {"name": target.name, "merged_order": source.name, "status": target.status,
		"subtotal": target.subtotal, "tax_total": target.tax_total, "grand_total": target.grand_total}


@frappe.whitelist()
def split_order(order_name, quantities, dining_table=None, source_check_label=None, split_check_label=None):
	"""Move selected quantities from an unconfirmed order into a new draft."""
	require_pos_action("can_split_orders")
	source = get_owned_draft_order(order_name)
	quantities = frappe.parse_json(quantities) or {}
	if not isinstance(quantities, dict) or not quantities:
		frappe.throw(_("Enter a quantity for at least one order line."))
	by_name = {row.name: row for row in source.items}
	for row_name, split_qty in quantities.items():
		row = by_name.get(row_name)
		qty = flt(split_qty)
		if not row or qty <= 0 or qty > flt(row.qty):
			frappe.throw(_("Each split quantity must be positive and no greater than its order line quantity."))
		if frappe.db.get_value("UOM", row.uom, "must_be_whole_number") and qty % 1:
			frappe.throw(_("Unit {0} does not allow fractional quantities.").format(row.uom))
	remaining_lines = [row for row in source.items if flt(row.qty) - flt(quantities.get(row.name)) > 0]
	if not remaining_lines:
		frappe.throw(_("At least one order line must remain on the source order."))
	if frappe.db.get_value("Order Type", source.order_type, "require_table") and not dining_table:
		frappe.throw(_("Choose a destination table for the split order."))
	labels = []
	for label in (source_check_label, split_check_label):
		if label is not None and not isinstance(label, str):
			frappe.throw(_("Check labels must be text."))
		label = label.strip() if label is not None else None
		if label and len(label) > 60:
			frappe.throw(_("Check labels cannot exceed 60 characters."))
		labels.append(label)
	if labels[0] and labels[1] and labels[0].casefold() == labels[1].casefold():
		frappe.throw(_("Choose a different label for each check."))
	if source_check_label is not None:
		source.check_label = labels[0]
	new_order = frappe.new_doc("POS Order")
	for fieldname in ("store", "cashier_session", "restaurant_brand", "order_type", "customer", "external_reference"):
		new_order.set(fieldname, source.get(fieldname))
	new_order.dining_table = dining_table
	new_order.check_label = labels[1]
	if dining_table and dining_table == source.dining_table:
		source.table_check_group = source.table_check_group or frappe.generate_hash(f"TABLE-CHECK|{source.name}", length=24)
		new_order.table_check_group = source.table_check_group
	if dining_table:
		table = frappe.db.get_value("Dining Table", dining_table, ["store", "dining_area", "enabled"], as_dict=True)
		if not table or table.store != source.store or not table.enabled:
			frappe.throw(_("Choose an enabled destination table in the same Store."))
		new_order.dining_area = table.dining_area
	for row in source.items:
		split_qty = flt(quantities.get(row.name))
		if split_qty:
			new_order.append("items", {"selling_product": row.selling_product, "option_parent": row.option_parent,
				"qty": split_qty, "notes": row.notes, "modifiers": row.modifiers})
			if split_qty < flt(row.qty):
				row.qty = flt(row.qty) - split_qty
	source.set("items", remaining_lines)
	source.save(ignore_permissions=True)
	new_order.insert(ignore_permissions=True)
	source.add_comment("Info", _("Quantities were split into order {0} by {1}.").format(new_order.name, frappe.session.user))
	new_order.add_comment("Info", _("Created by splitting order {0} by {1}.").format(source.name, frappe.session.user))
	return {"name": new_order.name, "source_order": source.name, "status": new_order.status,
		"subtotal": new_order.subtotal, "tax_total": new_order.tax_total, "grand_total": new_order.grand_total}


@frappe.whitelist()
def cancel_order(order_name):
	require_pos_action("can_cancel_orders")
	doc = frappe.get_doc("POS Order", order_name)
	assert_store_access(doc.store)
	require_order_scope(doc)
	session_user = frappe.db.get_value("Cashier Session", doc.cashier_session, "user") if doc.cashier_session else None
	manager = bool(set(frappe.get_roles()) & {"POS Manager", "System Manager"})
	if not session_user or (session_user != frappe.session.user and not manager):
		frappe.throw(_("This order does not belong to your Cashier Session."), frappe.PermissionError)
	if doc.status not in ("Open", "Pending Confirmation", "Confirmed", "In Preparation", "Ready"):
		frappe.throw(_("Only unpaid active orders can be cancelled."))
	if doc.status not in ("Open", "Pending Confirmation") and not manager:
		frappe.throw(_("A POS Manager must approve cancellation after kitchen confirmation."), frappe.PermissionError)
	for ticket_name in frappe.get_all("Kitchen Ticket", filters={"pos_order": doc.name}, pluck="name"):
		ticket = frappe.get_doc("Kitchen Ticket", ticket_name)
		if ticket.status not in ("Cancelled", "Picked"):
			ticket.set_status("Cancelled")
			area = frappe.get_doc("Preparation Area", ticket.preparation_area)
			if area.has_printer:
				key = frappe.generate_hash(f"{ticket.name}|CANCELLED", length=32)
				if not frappe.db.exists("Print Dispatch Job", {"idempotency_key": key}):
					frappe.get_doc({
						"doctype": "Print Dispatch Job", "store": doc.store,
						"preparation_area": area.name, "print_device": area.print_device,
						"document_type": "Kitchen Ticket", "document_name": ticket.name,
						"idempotency_key": key, "status": "Queued", "payload": "CANCELLED",
					}).insert(ignore_permissions=True)
	doc.reload()
	if doc.status not in ("Open", "Pending Confirmation", "Confirmed", "In Preparation", "Ready"):
		frappe.throw(_("Only unpaid active orders can be cancelled."))
	doc.status = "Cancelled"
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def cancel_confirmed_order_item(order_name, item_name, qty, reason):
	"""Manager-only, audited cancellation of a previously confirmed order line."""
	require_pos_action("can_cancel_orders")
	if not (set(frappe.get_roles()) & {"POS Manager", "System Manager"}):
		frappe.throw(_("A POS Manager must approve cancellation of an item already sent to preparation."), frappe.PermissionError)
	doc = frappe.get_doc("POS Order", order_name)
	assert_store_access(doc.store)
	require_order_scope(doc)
	if doc.cashier_session != frappe.db.get_value("Cashier Session", {"user": frappe.session.user, "status": ["in", ["Open", "Closing"]]}, "name"):
		require_pos_action("can_edit_open_orders")
	row = next((entry for entry in doc.items if entry.name == item_name), None)
	if not row:
		frappe.throw(_("The selected item does not belong to this order."))
	cancel_qty = validate_confirmed_item_cancellation(
		doc.status, row.sent_to_kitchen, row.qty, row.cancelled_qty, qty, reason, True
	)
	row.cancelled_qty = flt(row.cancelled_qty) + cancel_qty
	doc.append("item_cancellations", {
		"pos_order_item": row.name, "qty": cancel_qty, "reason": (reason or "").strip(),
		"cancelled_by": frappe.session.user, "cancelled_at": now_datetime(),
	})
	for ticket_name in frappe.get_all("Kitchen Ticket", filters={"pos_order": doc.name}, pluck="name"):
		ticket = frappe.get_doc("Kitchen Ticket", ticket_name)
		ticket_row = next((entry for entry in ticket.items if entry.pos_order_item == row.name), None)
		if not ticket_row:
			continue
		if ticket.status == "Picked":
			notice = frappe.new_doc("Kitchen Ticket")
			notice.pos_order = doc.name
			notice.store = doc.store
			notice.preparation_area = ticket.preparation_area
			notice.status = "Cancelled"
			notice.is_item_cancellation_notice = 1
			notice.cancellation_reason = (reason or "").strip()
			notice.append("items", {"pos_order_item": row.name, "selling_product": row.selling_product,
				"qty": cancel_qty, "cancelled_qty": cancel_qty, "status": "Cancelled", "notes": (reason or "").strip()})
			notice.insert(ignore_permissions=True)
			notice.flags.skip_order_status_sync = True
			notice.set_status("Cancelled")
			area = frappe.get_doc("Preparation Area", ticket.preparation_area)
			if area.has_printer:
				key = frappe.generate_hash(f"{notice.name}|ITEM-CANCEL-NOTICE", length=32)
				frappe.get_doc({"doctype": "Print Dispatch Job", "store": doc.store,
					"preparation_area": area.name, "print_device": area.print_device,
					"document_type": "Kitchen Ticket", "document_name": notice.name,
					"idempotency_key": key, "status": "Queued",
					"payload": f"CANCEL {cancel_qty:g} × {row.selling_product}: {(reason or '').strip()}"}).insert(ignore_permissions=True)
			continue
		ticket_row.cancelled_qty = flt(ticket_row.cancelled_qty) + cancel_qty
		ticket.save(ignore_permissions=True)
		if all(get_active_order_item_qty(entry.qty, entry.cancelled_qty) <= 0 for entry in ticket.items):
			ticket.flags.skip_order_status_sync = True
			ticket.set_status("Cancelled")
		area = frappe.get_doc("Preparation Area", ticket.preparation_area)
		if area.has_printer:
			key = frappe.generate_hash(f"{ticket.name}|ITEM-CANCEL|{row.name}|{row.cancelled_qty}", length=32)
			if not frappe.db.exists("Print Dispatch Job", {"idempotency_key": key}):
				frappe.get_doc({"doctype": "Print Dispatch Job", "store": doc.store,
					"preparation_area": area.name, "print_device": area.print_device,
					"document_type": "Kitchen Ticket", "document_name": ticket.name,
					"idempotency_key": key, "status": "Queued",
					"payload": f"CANCEL {cancel_qty:g} × {row.selling_product}: {(reason or '').strip()}"}).insert(ignore_permissions=True)
	doc.flags.allow_item_cancellation = True
	doc.flags.ignore_permissions = True
	if all(get_active_order_item_qty(entry.qty, entry.cancelled_qty) <= 0 for entry in doc.items):
		doc.status = "Cancelled"
	doc.recalculate_cancelled_item_amounts()
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "status": doc.status, "cancelled_qty": flt(row.cancelled_qty),
		"remaining_qty": get_active_order_item_qty(row.qty, row.cancelled_qty),
		"subtotal": doc.subtotal, "tax_total": doc.tax_total, "grand_total": doc.grand_total}


@frappe.whitelist()
def update_order_item_notes(order_name, item_name, notes):
	"""Save a note on an active order line that has not been sent to preparation."""
	require_pos_action("can_checkout")
	doc = frappe.get_doc("POS Order", order_name)
	assert_store_access(doc.store)
	require_order_scope(doc)
	session = get_user_session(doc.store)
	if not session or session.status != "Open":
		frappe.throw(_("Open your Cashier Session for this Store before editing an order."))
	if doc.cashier_session != session.name:
		require_pos_action("can_edit_open_orders")
	if doc.status not in ("Open", "Pending Confirmation", "Confirmed", "In Preparation", "Ready"):
		frappe.throw(_("Only active unpaid orders can be edited."), frappe.PermissionError)
	row = next((item for item in doc.get("items", []) if item.name == item_name), None)
	if not row:
		frappe.throw(_("The selected item does not belong to this order."), frappe.PermissionError)
	if row.sent_to_kitchen:
		frappe.throw(_("An item already sent to preparation cannot be edited."), frappe.PermissionError)
	if not isinstance(notes, str):
		frappe.throw(_("Enter a valid comment."))
	if len(notes) > 1000:
		frappe.throw(_("A comment cannot exceed 1000 characters."))
	frappe.db.set_value("POS Order Item", row.name, "notes", notes, update_modified=True)
	return {"name": row.name, "notes": notes}


@frappe.whitelist()
def save_order(order_data):
	require_pos_action("can_checkout")
	data = frappe.parse_json(order_data)
	store_doc = assert_store_access(data.get("store"))
	session = get_user_session(data.get("store"))
	if not session or session.status != "Open" or session.user != frappe.session.user:
		frappe.throw(_("Open your Cashier Session before saving an order."))

	append_mode = False
	if data.get("name"):
		doc = frappe.get_doc("POS Order", data["name"])
		if doc.cashier_session != session.name:
			require_pos_action("can_edit_open_orders")
			if doc.store != store_doc.name or doc.status not in ("Open", "Pending Confirmation", "Confirmed", "In Preparation", "Ready"):
				frappe.throw(_("Only active orders in this Store can receive items from another cashier."), frappe.PermissionError)
			append_mode = True
			doc.flags.allow_order_item_append = True
		require_order_scope(doc)
		if append_mode:
			pass
		elif doc.status in ("Confirmed", "In Preparation", "Ready"):
			append_mode = True
			doc.flags.allow_order_item_append = True
			for fieldname in ("store", "restaurant_brand", "order_type", "customer", "external_reference", "dining_area", "dining_table",
				"discount_type", "discount_scope", "discount_value", "discount_reason"):
				if (data.get(fieldname) or None) != (doc.get(fieldname) or None):
					frappe.throw(_("An order already sent to preparation can only receive new items."))
		elif doc.status in ("Open", "Pending Confirmation"):
			doc.set("items", [])
		else:
			frappe.throw(_("Only active unpaid orders can be edited."), frappe.PermissionError)
	else:
		doc = frappe.new_doc("POS Order")
		doc.store = store_doc.name
		doc.cashier_session = session.name
		doc.status = "Open"

	if not append_mode:
		for fieldname in ("restaurant_brand", "order_type", "customer", "external_reference", "dining_area", "dining_table",
			"discount_type", "discount_scope", "discount_value", "discount_reason"):
			doc.set(fieldname, data.get(fieldname))
	if doc.restaurant_brand not in {row["name"] for row in get_brands(store_doc.name)}:
		frappe.throw(_("Choose a Brand available to you in this Store."), frappe.PermissionError)
	if doc.order_type not in {row["name"] for row in get_order_types(store_doc.name)}:
		frappe.throw(_("Choose an Order Type available to you in this Store."), frappe.PermissionError)
	items_to_save = data.get("items") or []
	if append_mode and not items_to_save:
		return {"name": doc.name, "status": doc.status, "subtotal": doc.subtotal, "tax_total": doc.tax_total,
			"grand_total": doc.grand_total, "sales_taxes_and_charges_template": doc.sales_taxes_and_charges_template,
			"appended_items": []}
	appended_items = []
	for item in items_to_save:
		row = doc.append("items", {
			"selling_product": item.get("selling_product"),
			"option_parent": item.get("option_parent"),
			"qty": flt(item.get("qty") or 1),
			"notes": item.get("notes"),
			"modifiers": serialize_json_rows(
				[
					{
						"modifier_group": modifier.get("modifier_group"),
						"modifier_product": modifier.get("modifier_product"),
						"qty": flt(modifier.get("qty") or 1),
					}
					for modifier in item.get("modifiers") or []
				]
			),
		})
		appended_items.append({"client_key": str(item.get("client_key") or ""), "name": row.name})
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)
	return {"name": doc.name, "status": doc.status, "subtotal": doc.subtotal, "tax_total": doc.tax_total,
		"grand_total": doc.grand_total, "sales_taxes_and_charges_template": doc.sales_taxes_and_charges_template,
		"appended_items": appended_items}


@frappe.whitelist()
def confirm_order(order_name):
	require_pos_action("can_checkout")
	doc = frappe.get_doc("POS Order", order_name)
	assert_store_access(doc.store)
	require_order_scope(doc)
	if doc.cashier_session and frappe.db.get_value("Cashier Session", doc.cashier_session, "user") != frappe.session.user:
		session = get_user_session(doc.store)
		if not session or session.status != "Open":
			frappe.throw(_("Open your Cashier Session for this Store before confirming another cashier’s order."), frappe.PermissionError)
		require_pos_action("can_edit_open_orders")
	elif not doc.cashier_session:
		frappe.throw(_("This order is not assigned to a Cashier Session."), frappe.PermissionError)
	doc.flags.ignore_permissions = True
	doc.confirm()
	return {"name": doc.name, "status": doc.status, "tickets": frappe.get_all("Kitchen Ticket", filters={"pos_order": doc.name}, pluck="name")}


def pos_discount_approval_context_hash(order_name, requester, store, discount_type, discount_value, discount_reason, discount_scope):
	context = {
		"order": str(order_name), "requester": str(requester), "store": str(store),
		"type": str(discount_type), "value": format(flt(discount_value), ".6f"),
		"reason": str(discount_reason or "").strip(), "scope": str(discount_scope),
	}
	return hashlib.sha256(json.dumps(context, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def get_pos_discount_approvers(store, exclude_user=None):
	users = frappe.get_all("User", filters={"enabled": 1}, fields=["name", "full_name"], order_by="full_name asc")
	approvers = []
	for user in users:
		if user.name == exclude_user:
			continue
		roles = set(frappe.get_roles(user.name))
		if roles & {"POS Manager", "System Manager"} and _user_has_store_access(user.name, store):
			approvers.append({"user": user.name, "full_name": user.full_name or user.name})
	return approvers


def discount_exceeds_pos_user_limit(user, discount_type, discount_value, discount_scope, subtotal, grand_total):
	pos_user = frappe.db.get_value("POS User", {"user": user, "enabled": 1},
		["can_apply_manual_discount", "max_manual_discount_percent"], as_dict=True)
	if pos_user and not pos_user.can_apply_manual_discount:
		frappe.throw(_("Your POS User permissions do not allow manual discounts."), frappe.PermissionError)
	if not pos_user and set(frappe.get_roles(user)) & {"POS Manager", "System Manager"}:
		return False
	base = flt(subtotal) if discount_scope == "Net Total" else flt(grand_total)
	value = flt(discount_value)
	effective_percent = value if discount_type == "Percentage" else (value / base * 100 if base else 0)
	limit = flt(pos_user.max_manual_discount_percent if pos_user else 0)
	return effective_percent > limit


def validate_pos_discount_value(discount_type, discount_value, invoice_total):
	"""Reject discount values outside the payable invoice amount before calculation."""
	value = flt(discount_value)
	if discount_type not in ("Percentage", "Amount"):
		frappe.throw(_("Choose Percentage or Fixed Amount for the discount."))
	if value < 0:
		frappe.throw(_("Discount cannot be negative."))
	if discount_type == "Percentage" and value > 100:
		frappe.throw(_("Discount percentage cannot exceed 100%."))
	if discount_type == "Amount" and value > flt(invoice_total):
		frappe.throw(_("Discount amount cannot exceed the invoice total."))
	return value


def get_pos_discount_approval(doc, discount_type, discount_value, discount_reason, approval_code,
		approval_approver=None, consume=False):
	if not approval_code:
		return None
	from frappe.utils import now_datetime

	requester = frappe.session.user
	context_hash = pos_discount_approval_context_hash(doc.name, requester, doc.store, discount_type,
		discount_value, discount_reason, doc.discount_scope)
	challenge_names = frappe.get_all("Approval Challenge", filters={
		"subject_doctype": "POS Order", "subject_name": doc.name,
		"action": POS_DISCOUNT_APPROVAL_ACTION, "requester": requester,
		"approval_context_hash": context_hash, "approver": approval_approver or "", "status": "Issued",
		"expires_at": [">", now_datetime()],
	}, pluck="name", order_by="creation desc", limit=1)
	if not challenge_names:
		frappe.throw(_("No current manager code matches this order and discount. Ask a POS Manager to issue a new code."))
	challenge_name = challenge_names[0]
	if consume:
		frappe.db.sql("select name from `tabApproval Challenge` where name = %s for update", challenge_name)
	challenge = frappe.get_doc("Approval Challenge", challenge_name)
	if challenge.store != doc.store or challenge.requester != requester:
		frappe.throw(_("This manager code was issued for a different cashier or Store."), frappe.PermissionError)
	approver_roles = set(frappe.get_roles(challenge.approver))
	if challenge.approver == requester or not (approver_roles & {"POS Manager", "System Manager"}):
		frappe.throw(_("A different POS Manager must approve this discount."), frappe.PermissionError)
	if "System Manager" not in approver_roles and not _user_has_store_access(challenge.approver, doc.store):
		frappe.throw(_("The approving manager no longer has access to this Store."), frappe.PermissionError)
	challenge.verify_code(approval_code, consume=consume)
	return challenge.approver


def _get_discount_password_failure_count(cache_key):
	return int(frappe.cache().get_value(cache_key, shared=True) or 0)


def _record_discount_password_failure(cache_key, count):
	frappe.cache().set_value(cache_key, count, expires_in_sec=300, shared=True)


def _clear_discount_password_failures(cache_key):
	frappe.cache().delete_value(cache_key, shared=True)


def verify_pos_discount_manager_password(doc, approver, password, discount_type, discount_value, discount_reason):
	"""Verify an authorized manager's fixed approval password and mint a one-use token."""
	requester = frappe.session.user
	eligible_approvers = {row["user"] for row in get_pos_discount_approvers(doc.store, exclude_user=requester)}
	if approver not in eligible_approvers:
		frappe.throw(_("Choose a POS Manager with access to this Store."), frappe.PermissionError)
	if not password:
		frappe.throw(_("Enter the manager password."))

	cache_key = "rms:pos-discount-password-failures:" + hashlib.sha256(
		f"{requester}:{approver}".encode()).hexdigest()
	failed_attempts = _get_discount_password_failure_count(cache_key)
	if failed_attempts >= 5:
		frappe.throw(_("Manager password verification is locked for five minutes."))
	pos_user_name = frappe.db.get_value("POS User", {"user": approver, "enabled": 1}, "name")
	stored_password = None
	if pos_user_name:
		manager_pos_user = frappe.get_doc("POS User", pos_user_name)
		stored_password = manager_pos_user.get_password("discount_approval_password", raise_exception=False)
	if not stored_password or not hmac.compare_digest(str(stored_password), str(password)):
		_record_discount_password_failure(cache_key, failed_attempts + 1)
		frappe.throw(_("The manager approval password is incorrect."))
	_clear_discount_password_failures(cache_key)

	from frappe.utils import add_to_date, now_datetime
	from frappe.utils.password import passlibctx
	requester = frappe.session.user
	scope = getattr(doc, "discount_scope", None) or "Net Total"
	context_hash = pos_discount_approval_context_hash(doc.name, requester, doc.store, discount_type,
		discount_value, discount_reason, scope)
	token = secrets.token_urlsafe(32)
	challenge = frappe.new_doc("Approval Challenge")
	challenge.update({
		"store": doc.store, "subject_doctype": "POS Order", "subject_name": doc.name,
		"action": POS_DISCOUNT_APPROVAL_ACTION, "requester": requester, "approver": approver,
		"status": "Issued", "code_hash": passlibctx.hash(token),
		"approval_context_hash": context_hash, "expires_at": add_to_date(now_datetime(), minutes=5),
	})
	challenge.flags.from_pos_api = True
	challenge.insert(ignore_permissions=True)
	return {"approver": approver, "approval_token": token}


@frappe.whitelist()
def issue_pos_discount_approval_code(order_name, discount_type="Percentage", discount_value=0, discount_reason=""):
	approver = frappe.session.user
	if not (set(frappe.get_roles(approver)) & {"POS Manager", "System Manager"}):
		frappe.throw(_("Only a POS Manager can issue a discount approval code."), frappe.PermissionError)
	doc = frappe.get_doc("POS Order", order_name)
	assert_store_access(doc.store)
	require_order_scope(doc)
	if doc.status not in ("Confirmed", "In Preparation", "Ready") or doc.pos_invoice:
		frappe.throw(_("Only an unpaid confirmed order can receive a discount approval."))
	if not doc.cashier_session:
		frappe.throw(_("This order has no Cashier Session to approve."))
	requester = frappe.db.get_value("Cashier Session", doc.cashier_session, "user")
	if not requester or requester == approver:
		frappe.throw(_("The cashier and approving manager must be different users."), frappe.PermissionError)
	if not get_pos_capabilities(requester).get("can_apply_manual_discount"):
		frappe.throw(_("This cashier is not allowed to apply manual discounts."), frappe.PermissionError)
	store = frappe.get_doc("Store", doc.store)
	scope = store.manual_discount_scope or "Net Total"
	value = flt(discount_value)
	reason = (discount_reason or "").strip()
	if value <= 0 or not reason:
		frappe.throw(_("Enter a positive discount and its reason before requesting approval."))
	if discount_type not in ("Percentage", "Amount"):
		frappe.throw(_("Choose Percentage or Fixed Amount for the discount."))
	doc.discount_scope = scope
	doc.discount_type = discount_type
	doc.discount_value = value
	doc.discount_reason = reason
	normal_tax, normal_total = doc.calculate_tax_preview()
	validate_pos_discount_value(discount_type, value, normal_total)
	base = flt(doc.subtotal) if scope == "Net Total" else flt(normal_total)
	effective_percent = value if discount_type == "Percentage" else (value / base * 100 if base else 0)
	pos_user = frappe.db.get_value("POS User", {"user": requester, "enabled": 1},
		["can_apply_manual_discount", "max_manual_discount_percent"], as_dict=True)
	limit = flt(pos_user.max_manual_discount_percent if pos_user else 0)
	if effective_percent <= limit:
		frappe.throw(_("This discount is within the cashier's allowed limit and does not need manager approval."))
	context_hash = pos_discount_approval_context_hash(doc.name, requester, doc.store, discount_type, value, reason, scope)
	for row in frappe.get_all("Approval Challenge", filters={
		"subject_doctype": "POS Order", "subject_name": doc.name,
		"action": POS_DISCOUNT_APPROVAL_ACTION, "requester": requester, "status": "Issued",
	}, fields=["name"]):
		old = frappe.get_doc("Approval Challenge", row.name)
		old.status = "Revoked"
		old.flags.from_pos_api = True
		old.save(ignore_permissions=True)
	from frappe.utils import add_to_date, now_datetime
	from frappe.utils.password import passlibctx
	code = f"{secrets.randbelow(1_000_000):06d}"
	challenge = frappe.new_doc("Approval Challenge")
	challenge.update({
		"store": doc.store, "subject_doctype": "POS Order", "subject_name": doc.name,
		"action": POS_DISCOUNT_APPROVAL_ACTION, "requester": requester, "approver": approver,
		"status": "Issued", "code_hash": passlibctx.hash(code),
		"approval_context_hash": context_hash, "expires_at": add_to_date(now_datetime(), minutes=5),
	})
	challenge.flags.from_pos_api = True
	challenge.insert(ignore_permissions=True)
	return {"code": code, "expires_at": challenge.expires_at, "discount_type": discount_type,
		"discount_value": value, "discount_reason": reason, "cashier": requester}


@frappe.whitelist()
def preview_order_discount(order_name, discount_type="Percentage", discount_value=0, discount_reason="", approval_code=None,
		approval_approver=None, approval_method="OTP"):
	require_pos_action("can_checkout")
	doc = frappe.get_doc("POS Order", order_name)
	assert_store_access(doc.store)
	require_order_scope(doc)
	if doc.cashier_session != frappe.db.get_value("Cashier Session", {"user": frappe.session.user, "status": "Open", "store": doc.store}, "name"):
		frappe.throw(_("This order does not belong to your open Cashier Session."), frappe.PermissionError)
	store = frappe.get_doc("Store", doc.store)
	doc.discount_scope = store.manual_discount_scope or "Net Total"
	doc.discount_type = discount_type
	doc.discount_value = flt(discount_value)
	doc.discount_reason = (discount_reason or "").strip() or (_("Preview") if doc.discount_value else "")
	if doc.discount_value:
		require_pos_action("can_apply_manual_discount")
	from rms.rms.doctype.pos_order.pos_order import calculate_discount_amount
	normal_tax, normal_total = doc.calculate_tax_preview()
	validate_pos_discount_value(doc.discount_type, doc.discount_value, normal_total)
	requires_approval = discount_exceeds_pos_user_limit(frappe.session.user, doc.discount_type, doc.discount_value,
		doc.discount_scope, doc.subtotal, normal_total)
	approval_token = None
	approver = None
	if approval_code:
		if approval_method == "Password":
			password_approval = verify_pos_discount_manager_password(doc, approval_approver, approval_code,
				doc.discount_type, doc.discount_value, doc.discount_reason)
			approver = password_approval["approver"]
			approval_token = password_approval["approval_token"]
		else:
			approver = get_pos_discount_approval(doc, doc.discount_type, doc.discount_value, doc.discount_reason,
				approval_code, approval_approver)
	if requires_approval and not approver:
		doc.flags.discount_approval_authorized = True
		doc.validate_discount(doc.subtotal, normal_tax, normal_total)
		doc.discount_amount = calculate_discount_amount(doc.subtotal, normal_tax, doc.discount_type,
			doc.discount_value, doc.discount_scope, normal_total)
		tax_total, grand_total = doc.calculate_tax_preview(apply_discount=bool(doc.discount_value))
		return {"discount_scope": doc.discount_scope, "discount_amount": doc.discount_amount,
			"tax_total": tax_total, "grand_total": grand_total, "requires_manager_approval": True,
			"approvers": get_pos_discount_approvers(doc.store, exclude_user=frappe.session.user)}
	if approver:
		doc.flags.discount_approval_authorized = True
	doc.validate_discount(doc.subtotal, normal_tax, normal_total)
	doc.discount_amount = calculate_discount_amount(doc.subtotal, normal_tax, doc.discount_type,
		doc.discount_value, doc.discount_scope, normal_total)
	tax_total, grand_total = doc.calculate_tax_preview(apply_discount=bool(doc.discount_value))
	return {"discount_scope": doc.discount_scope, "discount_amount": doc.discount_amount,
		"tax_total": tax_total, "grand_total": grand_total, "requires_manager_approval": bool(approver),
		"approved_by": approver, "approval_token": approval_token}


def validate_guest_payment_rows(guest_rows, allowed_methods, allow_zero=False):
	"""Validate and normalize named checks used for a split payment."""
	if not guest_rows:
		return [], {}
	if not isinstance(guest_rows, list) or not 2 <= len(guest_rows) <= 10:
		frappe.throw(_("A split payment requires between two and ten guest checks."))

	seen_names = set()
	payment_totals = {}
	normalized_rows = []
	for guest in guest_rows:
		name = str(guest.get("guest") or "").strip() if isinstance(guest, dict) else ""
		method = str(guest.get("mode_of_payment") or "").strip() if isinstance(guest, dict) else ""
		amount = flt(guest.get("amount")) if isinstance(guest, dict) else 0
		if not name or method not in allowed_methods or amount < 0 or (amount == 0 and not allow_zero):
			frappe.throw(_("Enter a guest name, an available payment method and an amount greater than zero for each check."))
		name_key = name.casefold()
		if name_key in seen_names:
			frappe.throw(_("Guest names must be different for a split check."))
		seen_names.add(name_key)
		split_mode = str(guest.get("split_mode") or "people")
		if split_mode not in ("people", "items"):
			frappe.throw(_("Choose to split the check by people or by items."))
		items = guest.get("items") or []
		if not isinstance(items, list):
			frappe.throw(_("Guest item assignments must be a list."))
		normalized_rows.append({"guest": name, "mode_of_payment": method, "amount": amount,
			"due_amount": flt(guest.get("due_amount")), "items": items, "split_mode": split_mode})
		payment_totals[method] = payment_totals.get(method, 0) + amount
	return normalized_rows, payment_totals


def validate_payment_change(payment_rows, expected_total):
	"""Accept over-tender on any payment method and return the change due."""
	paid_total = sum(flt(row.get("amount")) for row in payment_rows)
	change_amount = max(0, paid_total - flt(expected_total))
	if paid_total + 0.01 < flt(expected_total):
		frappe.throw(_("Payment amounts must cover the displayed Grand Total."))
	return paid_total, change_amount


def allocate_change_to_order_payments(payment_rows, change_amount, cash_methods=()):
	"""Net tender rows stored on POS Order so they balance after invoice change is returned."""
	amounts = [flt(row.get("amount")) for row in payment_rows]
	change_left = flt(change_amount)
	priority = [index for index, row in enumerate(payment_rows) if row.get("mode_of_payment") in cash_methods]
	priority.extend(index for index, row in enumerate(payment_rows) if row.get("mode_of_payment") not in cash_methods)
	for index in priority:
		deduction = min(amounts[index], change_left)
		amounts[index] = max(0, amounts[index] - deduction)
		change_left = max(0, change_left - deduction)
		if change_left <= 0.005:
			break
	return [{**row, "amount": amount} for row, amount in zip(payment_rows, amounts) if amount > 0.005]


def ensure_payment_rows_for_total(payment_rows, allowed_methods, expected_total):
	"""Require tender for balances due; use a zero tender row for free POS invoices."""
	if payment_rows:
		return payment_rows
	if flt(expected_total) > 0.005:
		frappe.throw(_("Select at least one Mode of Payment."))
	if not allowed_methods:
		frappe.throw(_("Set at least one Mode of Payment on the cashier POS Profile."))
	# ERPNext requires a payment row on every POS Invoice. A free order uses an
	# enabled session method as a zero-value accounting row; the cashier tenders nothing.
	return [{"mode_of_payment": allowed_methods[0], "amount": 0}]


def validate_guest_item_allocations(guest_rows, active_item_names, expected_total):
	"""Check split shares and enforce complete, unique item assignments."""
	if not guest_rows:
		return
	modes = {row["split_mode"] for row in guest_rows}
	if len(modes) != 1:
		frappe.throw(_("Use one split method for all people on this check."))
	if abs(sum(row["due_amount"] for row in guest_rows) - flt(expected_total)) > 0.01:
		frappe.throw(_("Guest shares must add up to the order total."))
	if modes == {"items"}:
		assigned = [item for row in guest_rows for item in row["items"]]
		if len(assigned) != len(set(assigned)) or set(assigned) != set(active_item_names):
			frappe.throw(_("Assign every active order item to exactly one person."))


@frappe.whitelist()
def pay_order(order_name, payments, guest_breakdown=None, discount_type=None, discount_value=None, discount_reason=None,
		discount_approval_code=None, discount_approval_approver=None):
	require_pos_action("can_checkout")
	doc = frappe.get_doc("POS Order", order_name, for_update=True)
	assert_store_access(doc.store)
	require_order_scope(doc)
	if doc.cashier_session and frappe.db.get_value("Cashier Session", doc.cashier_session, "user") != frappe.session.user:
		frappe.throw(_("This order belongs to another Cashier Session."), frappe.PermissionError)
	if doc.pos_invoice:
		return {"pos_invoice": doc.pos_invoice, "status": doc.status}
	if doc.status not in ("Confirmed", "In Preparation", "Ready"):
		frappe.throw(_("Confirm the order before taking payment."))
	if discount_value is not None:
		store = frappe.get_doc("Store", doc.store)
		doc.discount_type = discount_type or "Percentage"
		doc.discount_scope = store.manual_discount_scope or "Net Total"
		doc.discount_value = flt(discount_value)
		doc.discount_reason = (discount_reason or "").strip()
		if doc.discount_value:
			require_pos_action("can_apply_manual_discount")
		doc.flags.allow_discount_update = True

	guest_rows = frappe.parse_json(guest_breakdown) if guest_breakdown else []
	payment_rows = frappe.parse_json(payments)
	allowed_payment_rows = session_payment_rows(doc.cashier_session)
	allowed_methods = {row.mode_of_payment for row in allowed_payment_rows}
	expected_grand_total = flt(doc.grand_total)
	selected_discount_approver = discount_approval_approver
	discount_approval_approver = None
	if discount_value is not None:
		from rms.rms.doctype.pos_order.pos_order import calculate_discount_amount

		normal_tax, normal_total = doc.calculate_tax_preview()
		validate_pos_discount_value(doc.discount_type, doc.discount_value, normal_total)
		discount_approval_approver = get_pos_discount_approval(doc, doc.discount_type, doc.discount_value,
			doc.discount_reason, discount_approval_code, approval_approver=selected_discount_approver)
		if discount_approval_approver:
			doc.flags.discount_approval_authorized = True
		doc.validate_discount(doc.subtotal, normal_tax, normal_total)
		doc.discount_amount = calculate_discount_amount(doc.subtotal, normal_tax, doc.discount_type,
			doc.discount_value, doc.discount_scope, normal_total)
		_discount_tax_total, expected_grand_total = doc.calculate_tax_preview(apply_discount=bool(doc.discount_value))
	guest_rows, payment_totals = validate_guest_payment_rows(
		guest_rows, allowed_methods, allow_zero=expected_grand_total <= 0.005)
	if guest_rows:
		payment_rows = [{"mode_of_payment": method, "amount": amount} for method, amount in payment_totals.items()]
	payment_rows = ensure_payment_rows_for_total(
		payment_rows, [row.mode_of_payment for row in allowed_payment_rows], expected_grand_total)
	seen_methods = set()
	for payment in payment_rows:
		method = payment.get("mode_of_payment")
		if method not in allowed_methods or method in seen_methods:
			frappe.throw(_("Choose each payment method once from this cashier session."))
		seen_methods.add(method)
		amount = flt(payment.get("amount"))
		if amount < 0 or (amount <= 0 and expected_grand_total > 0.005):
			frappe.throw(_("Payment amounts must be greater than zero."))
	active_items = [item.name for item in doc.items if get_active_order_item_qty(item.qty, item.cancelled_qty) > 0] if guest_rows else []
	validate_guest_item_allocations(guest_rows, active_items, expected_grand_total)
	paid_total, change_amount = validate_payment_change(payment_rows, expected_grand_total)
	if discount_value is not None:
		if discount_approval_code and discount_approval_approver:
			get_pos_discount_approval(doc, doc.discount_type, doc.discount_value, doc.discount_reason,
				discount_approval_code, approval_approver=discount_approval_approver, consume=True)
			doc.flags.discount_approval_authorized = True
		doc.save(ignore_permissions=True)

	session = frappe.get_doc("Cashier Session", doc.cashier_session)
	profile = frappe.get_doc("POS Profile", session.pos_profile)
	if change_amount and not profile.account_for_change_amount:
		frappe.throw(_("Set the Account for Change Amount on POS Profile {0} before accepting overpayment.").format(profile.name))
	customer = doc.customer or profile.customer
	if not customer:
		frappe.throw(_("Choose a Customer or set a default Customer on the POS Profile."))
	company = profile.company
	price_list = profile.selling_price_list
	if not price_list:
		frappe.throw(_("Set a Selling Price List on the POS Profile."))

	invoice = frappe.new_doc("POS Invoice")
	invoice.company = company
	invoice.customer = customer
	invoice.pos_profile = profile.name
	invoice.is_pos = 1
	invoice.posting_date = nowdate()
	invoice.selling_price_list = price_list
	invoice.taxes_and_charges = doc.sales_taxes_and_charges_template
	invoice.account_for_change_amount = profile.account_for_change_amount
	if guest_rows and frappe.get_meta("POS Invoice").has_field("rms_guest_payment_breakdown"):
		invoice.rms_guest_payment_breakdown = json.dumps(guest_rows, ensure_ascii=False)
	invoice.update_stock = int(bool(profile.update_stock) or any(
		frappe.db.get_value("Item", row.item, "is_stock_item") for row in doc.items
	))
	account_mapping = frappe.db.get_value(
		"Order Type Account Mapping",
		{"parent": doc.order_type, "parenttype": "Order Type", "company": company},
		["income_account", "cost_of_goods_sold_account"],
		as_dict=True,
	)
	if not account_mapping:
		frappe.throw(_("Add the Order Type account mapping for the POS Profile Company."))

	invoice_line_rates = []
	for row in doc.items:
		active_qty = get_active_order_item_qty(row.qty, row.cancelled_qty)
		if not active_qty:
			continue
		item_stock_uom = frappe.db.get_value("Item", row.item, "stock_uom")
		invoice_item = {
			"item_code": row.item,
			"item_name": frappe.db.get_value("Item", row.item, "item_name"),
			"qty": active_qty,
			"uom": row.uom,
			"stock_uom": item_stock_uom,
			"rate": row.selling_price,
			"price_list_rate": row.selling_price,
			"warehouse": row.warehouse if frappe.db.get_value("Item", row.item, "is_stock_item") else None,
			"income_account": account_mapping.income_account,
			"expense_account": account_mapping.cost_of_goods_sold_account,
			"rms_pos_order_item": row.name,
		}
		if row.uom == item_stock_uom:
			invoice_item["conversion_factor"] = 1
		invoice_row = invoice.append("items", invoice_item)
		invoice_line_rates.append((invoice_row, flt(row.selling_price), invoice_row.warehouse))
		for modifier in parse_json_rows(row.modifiers):
			modifier_product = frappe.get_doc("Selling Product", modifier.modifier_product)
			modifier_stock_uom = frappe.db.get_value("Item", modifier_product.item, "stock_uom")
			modifier_invoice_item = {
				"item_code": modifier_product.item,
				"item_name": frappe.db.get_value("Item", modifier_product.item, "item_name"),
			"qty": active_qty * flt(modifier.qty),
				"uom": modifier_product.uom,
				"stock_uom": modifier_stock_uom,
				"rate": modifier.selling_price,
				"price_list_rate": modifier.selling_price,
				"warehouse": modifier.warehouse if modifier_product.maintain_stock else None,
				"income_account": account_mapping.income_account,
				"expense_account": account_mapping.cost_of_goods_sold_account,
				"rms_pos_order_item": row.name,
			}
			if modifier_product.uom == modifier_stock_uom:
				modifier_invoice_item["conversion_factor"] = 1
			modifier_invoice_row = invoice.append("items", modifier_invoice_item)
			invoice_line_rates.append((modifier_invoice_row, flt(modifier.selling_price), modifier_invoice_row.warehouse))
	for index, payment in enumerate(payment_rows):
		invoice.append("payments", {
			"mode_of_payment": payment.get("mode_of_payment"),
			"amount": flt(payment.get("amount")),
			"default": 1 if index == 0 else 0,
		})

	# ERPNext checks Account read access while resolving party accounts. The cashier
	# is already authorized above by POS role, Store assignment, session ownership,
	# and exact payment validation, so keep the privileged work inside this block.
	actor = frappe.session.user
	try:
		frappe.set_user("Administrator")
		with allow_rms_cashier_session_pos_invoice(invoice, session, actor), prevent_pos_item_price_autoinsert(invoice):
			invoice.set_missing_values()
			_apply_order_tax_template(invoice, doc.sales_taxes_and_charges_template)
			_apply_order_discount(invoice, doc)
			for invoice_row, rate, warehouse in invoice_line_rates:
				invoice_row.rate = rate
				invoice_row.price_list_rate = rate
				if warehouse:
					invoice_row.warehouse = warehouse
			# Recalculate final totals using ERPNext's standard invoice rules.
			invoice.calculate_taxes_and_totals()
			if abs(flt(invoice.grand_total) - expected_grand_total) > 0.01:
				frappe.throw(_("ERPNext Invoice total {0} differs from the POS total {1}. Refresh the order and retry payment.").format(
					flt(invoice.grand_total, 2), flt(expected_grand_total, 2)))
			invoice.insert(ignore_permissions=True)
			# Keep the sale attributable to its cashier so the same session can return it.
			invoice.owner = actor
			frappe.db.set_value("POS Invoice", invoice.name, "owner", actor, update_modified=False)
			for invoice_row in invoice.items:
				frappe.db.set_value("POS Invoice Item", invoice_row.name, "owner", actor, update_modified=False)
			invoice.submit()
			if flt(doc.discount_amount) > 0 and doc.discount_reason:
				discount_comment = _("POS discount: {0} {1} on {2}. Reason: {3}. Applied by {4}.").format(
					doc.discount_value, doc.discount_type, doc.discount_scope, doc.discount_reason, actor)
				if discount_approval_approver:
					discount_comment += " " + _("Approved by {0} using a one-time manager code.").format(discount_approval_approver)
				invoice.add_comment("Info", discount_comment)
			recipe_stock_entry = create_recipe_stock_entry(doc, company, account_mapping.cost_of_goods_sold_account)
	finally:
		frappe.set_user(actor)

	doc.pos_invoice = invoice.name
	if recipe_stock_entry:
		doc.recipe_stock_entry = recipe_stock_entry
	doc.payments = []
	cash_methods = {payment.get("mode_of_payment") for payment in payment_rows
		if frappe.db.get_value("Mode of Payment", payment.get("mode_of_payment"), "type") == "Cash"}
	for payment in allocate_change_to_order_payments(payment_rows, change_amount, cash_methods):
		doc.append("payments", {"mode_of_payment": payment.get("mode_of_payment"), "amount": payment.get("amount")})
	if not doc.payments and expected_grand_total <= 0.005:
		doc.append("payments", {"mode_of_payment": payment_rows[0].get("mode_of_payment"), "amount": 0})
	doc.status = "Paid"
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	return {"pos_invoice": invoice.name, "status": doc.status, "grand_total": invoice.grand_total,
		"paid_total": paid_total, "change_amount": flt(invoice.change_amount or change_amount),
		"discount_approved_by": discount_approval_approver}




def create_recipe_stock_entry(order, company, expense_account):
	if order.recipe_stock_entry and frappe.db.get_value("Stock Entry", order.recipe_stock_entry, "docstatus") == 1:
		return order.recipe_stock_entry
	components = []
	for row in order.items:
		active_qty = get_active_order_item_qty(row.qty, row.cancelled_qty)
		if not active_qty or not flt(row.qty):
			continue
		ratio = active_qty / flt(row.qty)
		for component in parse_json_rows(row.recipe_snapshot):
			component.qty = flt(component.qty) * ratio
			components.append(component)
	return create_material_issue(
		company,
		components,
		expense_account,
		_("Recipe consumption for POS Order {0}").format(order.name),
	)


def session_payment_rows(session_name):
	return frappe.get_all("Cashier Session Payment", filters={"parent": session_name, "parenttype": "Cashier Session"},
		fields=["mode_of_payment"])


@frappe.whitelist()
def get_returnable_sales(store):
	require_pos_action("can_request_returns")
	assert_store_access(store)
	session = get_user_session(store)
	if not session or session.status != "Open":
		frappe.throw(_("Open a Cashier Session before processing a return."))
	orders = frappe.get_all("POS Order", filters={"cashier_session": session.name, "status": "Paid"},
		fields=["name", "restaurant_brand", "order_type"])
	orders = [row.name for row in orders if is_pos_scope_allowed("brand", row.restaurant_brand)
		and is_pos_scope_allowed("order_type", row.order_type)]
	if not orders:
		return []
	invoice_names = frappe.get_all("POS Order", filters={"name": ["in", orders]}, pluck="pos_invoice")
	invoice_names = [name for name in invoice_names if name]
	rows = frappe.get_all("POS Invoice", filters={
		"name": ["in", invoice_names], "docstatus": 1, "is_return": 0,
	}, fields=["name", "customer", "posting_date", "grand_total", "owner"], order_by="posting_date desc, modified desc")
	for row in rows:
		row["returnable_lines"] = get_returnable_sale_items(row.name, session=session)
	rows = [row for row in rows if row["returnable_lines"]]
	methods = frappe.get_all("POS Payment Method", filters={
		"parent": session.pos_profile, "parenttype": "POS Profile", "allow_in_returns": 1,
	}, fields=["mode_of_payment"], order_by="idx asc")
	return {"invoices": rows, "refund_methods": methods}


def get_returnable_sale_items(invoice_name, session=None):
	from rms.rms.doctype.pos_return.pos_return import POSReturn

	session = session or get_user_session()
	if not session or session.status != "Open":
		return []
	invoice = frappe.db.get_value("POS Invoice", invoice_name,
		["docstatus", "is_return", "pos_profile", "owner"], as_dict=True)
	if not invoice or invoice.docstatus != 1 or invoice.is_return or invoice.owner != session.user or invoice.pos_profile != session.pos_profile:
		return []
	order = frappe.db.get_value("POS Order", {"pos_invoice": invoice_name}, ["restaurant_brand", "order_type"], as_dict=True)
	if not order or not is_pos_scope_allowed("brand", order.restaurant_brand) or not is_pos_scope_allowed("order_type", order.order_type):
		return []
	rows = frappe.get_all("POS Invoice Item", filters={"parent": invoice_name, "parenttype": "POS Invoice"},
		fields=["name", "item_code", "qty", "rate", "amount", "warehouse", "uom", "rms_pos_order_item"], order_by="idx asc")
	result = []
	for row in rows:
		if not row.rms_pos_order_item:
			continue
		order_item = frappe.db.get_value("POS Order Item", row.rms_pos_order_item,
			["parent", "item", "modifiers"], as_dict=True)
		if not order_item:
			continue
		modifier_items = {item.get("item") for item in parse_json_rows(order_item.modifiers)}
		if order_item.item != row.item_code and row.item_code not in modifier_items:
			continue
		reserved = POSReturn.get_reserved_qty(row.name)
		remaining = flt(row.qty) - reserved
		if remaining > 0:
			row.update({"qty": remaining, "sold_qty": row.qty, "returned_qty": reserved,
				"title": frappe.db.get_value("Item", row.item_code, "item_name"),
				"must_be_whole_number": bool(frappe.db.get_value("UOM", row.uom, "must_be_whole_number"))})
			result.append(row)
	return result


@frappe.whitelist(methods=["POST"])
def request_pos_return(source_pos_invoice, items, payments, reason=None):
	require_pos_action("can_request_returns")
	items = frappe.parse_json(items or "[]")
	payments = frappe.parse_json(payments or "[]")
	if not isinstance(items, list) or not isinstance(payments, list):
		frappe.throw(_("Return items and refund payments must be lists."))
	session = get_user_session()
	if not session or session.status != "Open":
		frappe.throw(_("Open your Cashier Session before requesting a return."))
	assert_store_access(session.store)
	frappe.db.sql("select name from `tabPOS Invoice` where name = %s for update", source_pos_invoice)
	source = frappe.get_doc("POS Invoice", source_pos_invoice)
	allowed_lines = {row.name: row for row in get_returnable_sale_items(source_pos_invoice, session=session)}
	if not allowed_lines:
		frappe.throw(_("This POS Invoice has no returnable items in your active session."))
	ret = frappe.new_doc("POS Return")
	ret.store = session.store
	ret.cashier_session = session.name
	ret.source_pos_invoice = source.name
	ret.reason = reason
	for item in items:
		line_name = item.get("source_pos_invoice_item")
		if line_name not in allowed_lines:
			frappe.throw(_("Select return items from the source POS Invoice."))
		ret.append("items", {"source_pos_invoice_item": line_name,
			"qty": flt(item.get("qty")), "is_waste": int(bool(item.get("is_waste")))})
	for payment in payments:
		ret.append("payments", {"mode_of_payment": payment.get("mode_of_payment"), "amount": flt(payment.get("amount"))})
	ret.insert(ignore_permissions=True)
	return {"name": ret.name, "status": ret.status, "refund_total": ret.refund_total}


@frappe.whitelist(methods=["POST"])
def preview_pos_return(source_pos_invoice, items):
	require_pos_action("can_request_returns")
	items = frappe.parse_json(items or "[]")
	if not isinstance(items, list) or not items:
		frappe.throw(_("Select at least one return item."))
	session = get_user_session()
	if not session or session.status != "Open":
		frappe.throw(_("Open your Cashier Session before previewing a return."))
	assert_store_access(session.store)
	frappe.db.sql("select name from `tabPOS Invoice` where name = %s for update", source_pos_invoice)
	allowed_lines = {row.name for row in get_returnable_sale_items(source_pos_invoice, session=session)}
	ret = frappe.new_doc("POS Return")
	ret.store = session.store
	ret.cashier_session = session.name
	ret.source_pos_invoice = source_pos_invoice
	seen = set()
	for item in items:
		line_name = item.get("source_pos_invoice_item")
		if line_name not in allowed_lines or line_name in seen:
			frappe.throw(_("Select unique return lines from the source POS Invoice."))
		seen.add(line_name)
		ret.append("items", {"source_pos_invoice_item": line_name, "qty": flt(item.get("qty")),
			"is_waste": int(bool(item.get("is_waste")))})
	for row in ret.items:
		ret.validate_return_line(row)
	invoice = ret.build_return_invoice()
	from rms.rms.doctype.pos_return.pos_return import get_return_refund_total
	return {"refund_total": get_return_refund_total(invoice),
		"currency": invoice.currency}


@frappe.whitelist(methods=["POST"])
def approve_pos_return(return_name):
	if frappe.session.user == "Guest" or not (set(frappe.get_roles()) & {"POS Manager", "System Manager"}):
		frappe.throw(_("Only a POS Manager can approve a return."), frappe.PermissionError)
	ret = frappe.get_doc("POS Return", return_name)
	assert_store_access(ret.store)
	order = frappe.db.get_value("POS Order", {"pos_invoice": ret.source_pos_invoice}, ["restaurant_brand", "order_type"], as_dict=True)
	if order:
		require_order_scope(order)
	if ret.status == "Approved" and ret.return_pos_invoice:
		return {"name": ret.name, "status": ret.status, "return_pos_invoice": ret.return_pos_invoice,
			"stock_entry": ret.stock_entry}
	if ret.status != "Pending Approval":
		frappe.throw(_("Only a return Pending Approval can be approved."))
	session = frappe.get_doc("Cashier Session", ret.cashier_session)
	if session.status != "Open":
		frappe.throw(_("The cashier session must remain Open through return approval."))
	frappe.db.sql("select name from `tabPOS Invoice` where name = %s for update", ret.source_pos_invoice)
	ret.validate_request()
	invoice = ret.build_return_invoice()
	profile = frappe.get_doc("POS Profile", session.pos_profile)
	profile_methods = {row.mode_of_payment for row in profile.payments}
	if any(row.mode_of_payment not in profile_methods for row in ret.payments):
		frappe.throw(_("A refund Mode of Payment is no longer enabled on the cashier POS Profile."))
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account

	invoice.set("payments", [])
	for index, payment in enumerate(ret.payments):
		invoice.append("payments", {
			"mode_of_payment": payment.mode_of_payment,
			"amount": -flt(payment.amount),
			"default": 1 if index == 0 else 0,
			"account": get_bank_cash_account(payment.mode_of_payment, invoice.company).get("account"),
			"type": frappe.db.get_value("Mode of Payment", payment.mode_of_payment, "type"),
		})
	refund_amount = sum(flt(row.amount) for row in ret.payments)
	invoice.paid_amount = -refund_amount
	invoice.base_paid_amount = -refund_amount * flt(invoice.conversion_rate or 1)
	invoice.change_amount = 0
	invoice.base_change_amount = 0
	from rms.rms.doctype.pos_return.pos_return import get_return_refund_total
	if abs(get_return_refund_total(invoice) - flt(ret.refund_total)) > 0.01:
		frappe.throw(_("The ERPNext Credit Note total changed. Refresh the return and submit it again."))
	manager = frappe.session.user
	actor = frappe.session.user
	try:
		frappe.set_user("Administrator")
		with prevent_pos_item_price_autoinsert(invoice):
			invoice.flags.ignore_permissions = True
			invoice.insert(ignore_permissions=True)
			invoice.owner = manager
			frappe.db.set_value("POS Invoice", invoice.name, "owner", manager, update_modified=False)
			invoice.submit()
		company = frappe.db.get_value("Store", ret.store, "company")
		stock_items = ret.build_stock_receipt_items()
		from rms.stock import create_material_receipt

		stock_entry = create_material_receipt(company, stock_items,
			_("POS return {0}: good items returned to inventory").format(ret.name))
	finally:
		frappe.set_user(actor)
	ret.return_pos_invoice = invoice.name
	ret.stock_entry = stock_entry
	ret.status = "Approved"
	ret.approved_by = manager
	ret.approved_at = now_datetime()
	ret.flags.allow_workflow_update = True
	ret.save(ignore_permissions=True)
	return {"name": ret.name, "status": ret.status, "return_pos_invoice": invoice.name, "stock_entry": stock_entry}


@frappe.whitelist(methods=["POST"])
def reject_pos_return(return_name, reason=None):
	if frappe.session.user == "Guest" or not (set(frappe.get_roles()) & {"POS Manager", "System Manager"}):
		frappe.throw(_("Only a POS Manager can reject a return."), frappe.PermissionError)
	ret = frappe.get_doc("POS Return", return_name)
	assert_store_access(ret.store)
	order = frappe.db.get_value("POS Order", {"pos_invoice": ret.source_pos_invoice}, ["restaurant_brand", "order_type"], as_dict=True)
	if order:
		require_order_scope(order)
	if ret.status != "Pending Approval":
		frappe.throw(_("Only a return Pending Approval can be rejected."))
	ret.status = "Rejected"
	ret.rejected_by = frappe.session.user
	ret.rejected_at = now_datetime()
	if reason:
		ret.reason = reason
	ret.flags.allow_workflow_update = True
	ret.save(ignore_permissions=True)
	return {"name": ret.name, "status": ret.status}
