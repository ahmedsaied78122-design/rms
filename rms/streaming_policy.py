"""RMS-owned streaming defaults and Store-based routing; no remote activation."""

import hashlib

import frappe
from frappe import _

MASTER_DATA = (
	"Branch",
	"Fiscal Year",
	"Company",
	"Currency",
	"Country",
	"UOM",
	"Item Group",
	"Brand",
	"Item Attribute",
	"Manufacturer",
	"Item",
	"Account",
	"Cost Center",
	"Warehouse",
	"Mode of Payment",
	"Tax Category",
	"Item Tax Template",
	"Sales Taxes and Charges Template",
	"Purchase Taxes and Charges Template",
	"Terms and Conditions",
	"Price List",
	"Address Template",
	"Supplier Group",
	"Territory",
	"Loyalty Program",
	"Restaurant Brand",
	"Order Type",
	"Modifier Group",
	"Product Category",
	"Store Menu",
	"Selling Product",
	"Store",
	"POS Profile",
	"POS User",
	"Preparation Area",
	"Dining Area",
	"Dining Table",
	"Expense Category",
	"POS Action Reason",
	"Print Device",
)
BOTH_DATA = ("Customer", "Contact", "Address", "Customer Group", "Industry Type")
ERP_TRANSACTIONS = (
	"POS Opening Entry",
	"POS Invoice",
	"POS Closing Entry",
	"Sales Invoice",
	"Stock Entry",
	"Journal Entry",
)
RMS_OPERATIONS = (
	"Cashier Session",
	"POS Order",
	"Kitchen Ticket",
	"POS Return",
	"Shift Expense",
	"Waste Entry",
)
LOCAL_TYPES = (
	"Approval Challenge",
	"Print Dispatch Job",
	"RMS Sync Event",
	"RMS Sync Settings",
	"Item Price",
	"Loyalty Point Entry",
	"POS Invoice Merge Log",
)


def defaults():
	"""Independent RMS policy, expressed through the existing Streaming Rule contract."""
	rows = []
	base = dict(
		enabled=1,
		all_branches=1,
		on_duplicated_insert="Update",
		include_files=1,
		include_passwords=0,
		event_create=1,
		event_update=1,
		event_submit=1,
		event_cancel=1,
		event_rename=1,
		event_delete=0,
		allow_rename=0,
		prevent_delete=1,
		prevent_local_delete=1,
		allow_local_rename=1,
		sync_events_after_submit=1,
	)
	for index, dt in enumerate(MASTER_DATA):
		rows.append(
			dict(
				base,
				doctype_name=dt,
				direction="Master to Slave",
				scope="Shared",
				priority=10 + index,
				lock_documents=1,
				lock_documents_after_submit=1,
				allow_creation=0,
				allow_amend=0,
				conditions="",
			)
		)
	for index, dt in enumerate(BOTH_DATA):
		rows.append(
			dict(
				base,
				doctype_name=dt,
				direction="Both",
				scope="Shared",
				priority=60 + index,
				lock_documents=0,
				lock_documents_after_submit=0,
				allow_creation=1,
				allow_amend=0,
				allow_local_rename=0,
				conditions="",
			)
		)
	# User definitions are centrally owned; credentials/session data stay local.
	rows.append(
		dict(
			base,
			doctype_name="User",
			direction="Master to Slave",
			scope="Shared",
			priority=8,
			lock_documents=1,
			allow_creation=0,
			allow_amend=0,
			allow_local_rename=0,
			conditions='doc.name not in ["Administrator", "Guest"]',
		)
	)
	for index, dt in enumerate(ERP_TRANSACTIONS):
		condition = "doc.docstatus > 0"
		if dt == "POS Closing Entry":
			condition = 'doc.docstatus > 0 and doc.status in ["Submitted", "Cancelled"]'
		rows.append(
			dict(
				base,
				doctype_name=dt,
				direction="Slave to Master",
				scope="Branch",
				branch_field="app:rms_store",
				priority=100 + index,
				lock_documents=1,
				lock_documents_after_submit=1,
				allow_creation=0,
				allow_amend=0,
				allow_local_rename=0,
				conditions=condition,
			)
		)
	for index, dt in enumerate(RMS_OPERATIONS):
		rows.append(
			dict(
				base,
				doctype_name=dt,
				direction="Slave to Master",
				scope="Branch",
				branch_field="store.streaming_branch",
				priority=120 + index,
				lock_documents=1,
				lock_documents_after_submit=1,
				allow_creation=0,
				allow_amend=0,
				allow_local_rename=0,
				conditions="",
			)
		)
	return rows


def rule_name(doctype):
	return "RMS-" + hashlib.sha256(doctype.encode()).hexdigest()[:20]


def connection_defaults(kind, role):
	"""Suggest only catalog/customers on a new slave; never reset saved copies."""
	if kind != "initial" or role != "Slave":
		return []
	from arab_streaming.streaming.adapters import is_business_doctype

	return [
		dict(
			doctype_name=row["doctype_name"],
			conditions=row.get("conditions") or "",
			mandatory=0,
			ignore_links=0,
			skip_if_exists=1,
			skip_links_if_exists=1,
			ignore_branch=0,
		)
		for row in defaults()
		if row["direction"] in ("Master to Slave", "Both")
		and row["doctype_name"] not in ("UOM", "Item Group")
		and is_business_doctype(row["doctype_name"])
	]


def ensure_defaults():
	"""Fill absent defaults only; never reset an operator's edits or a slave's publication."""
	if not frappe.db.exists("DocType", "Streaming Rule"):
		return
	if frappe.conf.get("arab_streaming_site_role") == "Slave":
		return
	from arab_streaming.streaming.adapters import is_business_doctype
	from arab_streaming.streaming.policy import validate_branch_path

	for values in defaults():
		dt = values["doctype_name"]
		if not is_business_doctype(dt) or frappe.db.exists(
			"Streaming Rule", {"doctype_name": dt}
		):
			continue
		meta = frappe.get_meta(dt)
		if meta.is_submittable and values["scope"] == "Shared":
			continue
		if values.get("branch_field"):
			validate_branch_path(dt, values["branch_field"])
		doc = frappe.get_doc(dict(doctype="Streaming Rule", **values))
		doc.insert(set_name=rule_name(dt))


def _assignment(doctype, name):
	assignment = frappe.db.get_value(
		"Streaming Branch Assignment",
		{"reference_doctype": doctype, "reference_name": name},
	)
	return (
		set(
			frappe.get_all(
				"Streaming Rule Branch",
				filters={
					"parent": assignment,
					"parenttype": "Streaming Branch Assignment",
				},
				pluck="branch",
			)
		)
		if assignment
		else set()
	)


def _store_branches(stores):
	stores = set(filter(None, stores))
	return (
		set(
			filter(
				None,
				frappe.get_all(
					"Store",
					filters={"name": ["in", list(stores)]},
					pluck="streaming_branch",
				),
			)
		)
		if stores
		else set()
	)


def resolve_branch(document, config, peer=None, incoming=False):
	"""Use declared associations first; a paired slave owns newly originated ERP records."""
	dt, name = document.get("doctype"), document.get("name")
	if dt not in ERP_TRANSACTIONS:
		frappe.throw(_("This RMS Branch resolver is reserved for ERP transactions."))
	assigned = _assignment(dt, name) if name else set()
	if assigned:
		return assigned
	stores = set()
	profile = document.get("pos_profile")
	if profile:
		stores.update(
			frappe.get_all("Store", filters={"pos_profile": profile}, pluck="name")
		)
		stores.update(
			frappe.get_all(
				"POS User Store",
				filters={"pos_profile": profile, "parenttype": "POS User"},
				pluck="store",
			)
		)
	# Foreign keys on the RMS wrapper are a reliable reverse association.
	for root, field in [
		("POS Order", "pos_invoice"),
		("POS Order", "recipe_stock_entry"),
		("Cashier Session", "pos_opening_entry"),
		("Cashier Session", "pos_closing_entry"),
		("Shift Expense", "journal_entry"),
		("Waste Entry", "stock_entry"),
		("POS Return", "return_pos_invoice"),
		("POS Return", "stock_entry"),
		("POS Return", "waste_stock_entry"),
	]:
		link = frappe.get_meta(root).get_field(field)
		if name and link and link.options == dt:
			stores.update(frappe.get_all(root, filters={field: name}, pluck="store"))
	branches = _store_branches(stores)
	paired = None
	role = frappe.conf.get("arab_streaming_site_role")
	if role == "Slave":
		peers = frappe.get_all(
			"Master Instance", filters={"enabled": 1}, pluck="restaurant_branch"
		)
		if len(set(peers)) == 1:
			paired = peers[0]
	elif incoming and role == "Master" and peer and not frappe.db.exists(dt, name):
		paired = peer.restaurant_branch
	if paired:
		if branches and branches != {paired}:
			frappe.throw(
				_("This transaction belongs to a different streaming Branch."),
				frappe.PermissionError,
			)
		company = document.get("company")
		companies = set(
			frappe.get_all(
				"Store", filters={"streaming_branch": paired}, pluck="company"
			)
		)
		if company and (not companies or company not in companies):
			frappe.throw(
				_("The transaction Company does not match the paired Store."),
				frappe.PermissionError,
			)
		return {paired}
	return branches


def remember_branch(peer, source, target, config):
	if not config or config.get("branch_field") != "app:rms_store":
		return
	from arab_streaming.streaming.context import replay_source

	if not replay_source():
		frappe.throw(
			_(
				"Only authenticated streaming may assign an imported transaction Branch."
			),
			frappe.PermissionError,
		)
	if target.doctype not in ERP_TRANSACTIONS:
		return
	branch = peer.get("restaurant_branch")
	if not branch:
		frappe.throw(_("A paired Branch is required for this transaction."))
	existing = _assignment(target.doctype, target.name)
	if existing:
		if existing != {branch}:
			frappe.throw(
				_("Streaming cannot transfer a transaction to another Branch."),
				frappe.PermissionError,
			)
		return
	frappe.get_doc(
		dict(
			doctype="Streaming Branch Assignment",
			reference_doctype=target.doctype,
			reference_name=target.name,
			branches=[{"branch": branch}],
		)
	).insert(ignore_permissions=True)
