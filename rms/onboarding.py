"""First-run Master/Slave setup, using Arab Streaming's authenticated bootstrap."""

import re
from types import SimpleNamespace

import frappe
from frappe import _

STATE_KEY = "rms_slave_setup"
SETUP_METHOD = "frappe.desk.page.setup_wizard.setup_wizard.setup_complete"


def install_defaults():
	# Branding saves System Settings before the native first-run language screen.
	for field, default in (("language", "en"), ("time_zone", "UTC")):
		if not frappe.db.get_single_value("System Settings", field):
			frappe.db.set_single_value("System Settings", field, default)


def preserve_pending_slave_setup():
	"""Company scaffolds must not make a migration finish an incomplete copy."""
	state = _state()
	if frappe.conf.get("arab_streaming_site_role") != "Slave" or not state.connection:
		return
	if (
		frappe.db.get_value("Master Instance", state.connection, "syncing_status")
		== "Complete"
	):
		return
	for app in ("frappe", "erpnext"):
		frappe.db.set_value(
			"Installed Application", {"app_name": app}, "is_setup_complete", 0
		)
	frappe.db.set_single_value("System Settings", "setup_complete", 0)
	frappe.clear_cache()


def _administrator():
	if frappe.session.user != "Administrator":
		frappe.throw(
			_("Only Administrator can configure this installation."),
			frappe.PermissionError,
		)


def _fresh():
	_administrator()
	if frappe.is_setup_complete():
		frappe.throw(_("This installation has already completed setup."))
	from arab_streaming import __version__
	from packaging.version import Version

	if Version(__version__) < Version("0.2.1"):
		frappe.throw(
			_("Update Arab Streaming to version 0.2.1 or later before Slave setup.")
		)


def _state():
	return frappe._dict(frappe.conf.get(STATE_KEY) or {})


def _configure(**values):
	from frappe.installer import update_site_config

	for key, value in values.items():
		update_site_config(key, value)


@frappe.whitelist(methods=["POST"])
def complete_master(args):
	"""Keep the native wizard intact; never let it create a slave's company."""
	_administrator()
	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

	if frappe.is_setup_complete():
		return {"status": "ok"}
	values = frappe.parse_json(args) if isinstance(args, str) else args
	if (
		not isinstance(values, dict)
		or values.get("rms_site_type", "Master") != "Master"
	):
		frappe.throw(_("Use the Slave connection screen to set up a slave."))
	if _state() or (
		frappe.conf.get("arab_streaming_site_role") == "Slave"
		and frappe.db.exists("Master Instance")
	):
		frappe.throw(
			_("Resume the existing Slave setup instead of creating a company.")
		)
	_configure(arab_streaming_site_role="Master")
	return setup_complete(values)


def master_setup_success(args):
	if frappe.conf.get("arab_streaming_site_role") == "Master":
		_configure(arab_streaming_enabled=1)


@frappe.whitelist(methods=["POST"])
def master_choices(protocol, version):
	"""Extend the existing, allowlisted Branch wire endpoint with permitted Stores."""
	from arab_streaming.api.connection import branches

	result = branches(protocol, version)  # Native wire authentication and role checks.
	if not frappe.conf.get("arab_streaming_enabled") or not frappe.is_setup_complete():
		frappe.throw(_("Complete the master setup and enable streaming first."))
	stores = (
		frappe.get_list(
			"Store",
			filters={"enabled": 1, "streaming_branch": ["in", result["branches"]]},
			fields=["name", "title", "streaming_branch", "company"],
			order_by="title",
			limit_page_length=100,
		)
		if result["branches"]
		else []
	)
	companies = (
		frappe.get_list(
			"Company",
			fields=[
				"name",
				"company_name",
				"abbr",
				"country",
				"default_currency",
				"parent_company",
				"is_group",
			],
			limit_page_length=100,
		)
		if stores
		else []
	)
	return {**result, "rms_stores": stores, "rms_companies": companies}


def _choices(master_url, access_key, secret):
	from arab_streaming.streaming.client import remote_call
	from arab_streaming.streaming.connections import validate_version
	from arab_streaming.streaming.validation import normalize_site_url

	url = normalize_site_url(master_url)
	if url == normalize_site_url(frappe.utils.get_url()):
		frappe.throw(_("The master must be a different site."))
	if not all(
		isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9]{15}", v)
		for v in (access_key, secret)
	):
		frappe.throw(
			_("Enter the Access Key and Secret from an enabled master Instance Key.")
		)
	connection = SimpleNamespace(
		doctype="Master Instance",
		domain=url,
		access_key=access_key,
		get_password=lambda field: secret,
	)
	facts = remote_call(connection, "arab_streaming.api.connection.capabilities")
	validate_version(facts.get("protocol"), facts.get("version"))
	if facts.get("role") != "Master":
		frappe.throw(_("The selected site is not a streaming master."))
	result = remote_call(connection, "arab_streaming.api.connection.branches")
	if not isinstance(result.get("rms_stores"), list):
		frappe.throw(_("Update RMS on the master to support Slave setup."))
	stores = [
		row
		for row in result["rms_stores"]
		if isinstance(row, dict)
		and all(
			isinstance(row.get(k), str) and row[k]
			for k in ("name", "streaming_branch", "company")
		)
		and row["streaming_branch"] in result.get("branches", [])
	]
	if not stores:
		frappe.throw(
			_(
				"No available Store was found. Enable its Streaming Branch on the master and grant the key user Store access."
			)
		)
	companies = result.get("rms_companies")
	if not isinstance(companies, list) or not companies or len(companies) > 100:
		frappe.throw(
			_(
				"The master did not supply Company setup details. Update RMS on the master."
			)
		)
	return url, stores, companies


@frappe.whitelist(methods=["POST"])
def test_master(master_url, access_key, secret):
	_fresh()
	frappe.flags.disable_traceback = True
	url, stores, _companies = _choices(master_url, access_key, secret)
	return {"master_url": url, "stores": stores}


def _integration_user():
	from arab_streaming.streaming.connections import site_id

	user = "rms-streaming-" + site_id().replace("-", "") + "@rms.invalid"
	if not frappe.db.exists("User", user):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": user,
				"first_name": "RMS Streaming",
				"enabled": 1,
				"user_type": "System User",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
	return user


@frappe.whitelist(methods=["POST"])
def start_slave(master_url, access_key, secret, store, site_url):
	_fresh()
	frappe.flags.disable_traceback = True
	from arab_streaming.streaming.validation import normalize_site_url
	from frappe.utils.synchronization import filelock

	with filelock("rms_slave_setup"):
		if _state():
			frappe.throw(_("A Slave setup already exists. Use Resume synchronization."))
		if (
			frappe.db.exists("Company")
			or frappe.db.exists("Master Instance")
			or frappe.db.exists("Slave Instance")
		):
			frappe.throw(
				_(
					"Slave setup requires a fresh installation without a company or existing connections."
				)
			)
		url, stores, companies = _choices(master_url, access_key, secret)
		selected = next((s for s in stores if s["name"] == store), None)
		if not selected:
			frappe.throw(_("Select an available Store returned by the master."))
		public_url = normalize_site_url(site_url)
		if public_url == url:
			frappe.throw(_("The slave and master must have different site URLs."))
		_configure(arab_streaming_site_role="Slave", arab_streaming_enabled=0)
		user = _integration_user()
		doc = frappe.get_doc(
			{
				"doctype": "Master Instance",
				"domain": url,
				"site_domain": public_url,
				"access_key": access_key,
				"secret": secret,
				"execution_user": user,
			}
		).insert(ignore_permissions=True)
		# Commit the encrypted connection before recording its durable resume identity.
		frappe.db.commit()
		_configure(
			**{
				STATE_KEY: {
					"connection": doc.name,
					"store": store,
					"branch": selected["streaming_branch"],
					"company": selected["company"],
					"master_url": url,
					"companies": companies,
				},
				"arab_streaming_public_url": public_url,
			}
		)
		return _resume()


def _prepare_copy(doc):
	from arab_streaming.streaming.connections import peer_state
	from arab_streaming.streaming.delivery import synchronize_policy
	from arab_streaming.streaming.guards import system_write
	from arab_streaming.streaming.policy import stored_rules

	synchronize_policy(doc, force=True)
	state = peer_state(doc.doctype, doc.name)
	if state.policy_errors:
		frappe.throw(
			_("The master's streaming rules need attention before setup can continue.")
		)
	# Only approved inbound definitions; never include transaction history in first-run setup.
	from rms.streaming_policy import BOTH_DATA, MASTER_DATA

	allowed = set(MASTER_DATA) | set(BOTH_DATA)
	rows = sorted(
		(
			r
			for r in stored_rules()
			if r.enabled
			and r.doctype_name in allowed
			and r.direction in ("Master to Slave", "Both")
		),
		key=lambda r: r.priority or 0,
	)
	if not {"Company", "Store", "Branch"}.issubset({r.doctype_name for r in rows}):
		frappe.throw(
			_("The master must publish Company, Store and Branch for initial setup.")
		)
	if len(rows) > 50:
		frappe.throw(_("The initial setup exceeds the supported copy size."))
	with system_write():
		doc.reload()
		doc.initial_sync_doctypes = []
		for rule in rows:
			doc.append(
				"initial_sync_doctypes",
				{
					"doctype_name": rule.doctype_name,
					"conditions": rule.conditions,
					"scope": rule.scope,
					"branch_field": rule.branch_field,
					"rule_id": rule.name,
					"rule_revision": rule.revision,
					"skip_if_exists": int(rule.doctype_name != "Company"),
					"skip_links_if_exists": 1,
				},
			)
		doc.save(ignore_permissions=True)
	_scaffold_companies(doc)


def _scaffold_companies(doc):
	"""Break Company/Account cycles without generating a local chart of accounts."""
	from arab_streaming.streaming.connections import peer_state
	from arab_streaming.streaming.context import replay

	from rms.setup_company import scaffolding

	state = peer_state(doc.doctype, doc.name)
	pending = list(_state().companies or [])
	with replay(state.pairing_id, state.execution_user), scaffolding():
		while pending:
			ready = [
				c
				for c in pending
				if isinstance(c, dict)
				and c.get("name")
				and (
					not c.get("parent_company")
					or frappe.db.exists("Company", c["parent_company"])
				)
			]
			if not ready:
				frappe.throw(
					_("The master's Company hierarchy is incomplete or inaccessible.")
				)
			for values in ready:
				if not frappe.db.exists("Company", values["name"]):
					fields = {
						k: values.get(k)
						for k in (
							"company_name",
							"abbr",
							"country",
							"default_currency",
							"parent_company",
							"is_group",
						)
					}
					frappe.get_doc(dict(doctype="Company", **fields)).insert(
						set_name=values["name"]
					)
				pending.remove(values)


def _resume():
	from arab_streaming.streaming.connections import link_connection, peer_state
	from arab_streaming.streaming.context import replay
	from arab_streaming.streaming.initial_sync import start

	state = _state()
	if not state.connection or frappe.conf.get("arab_streaming_site_role") != "Slave":
		frappe.throw(_("No Slave setup is available to resume."))
	doc = frappe.get_doc("Master Instance", state.connection)
	if doc.syncing_status in ("Complete", "In Progress"):
		return {"status": doc.syncing_status}
	if doc.connection_status != "Connected":
		link_connection(doc.name, state.branch)
		doc.reload()
	_configure(arab_streaming_enabled=1)
	# Provision the local receiver identity under its authenticated pairing. Its
	# app-managed roles must not be treated as an operator editing master-owned Users.
	paired = peer_state(doc.doctype, doc.name)
	with replay(paired.pairing_id, paired.execution_user):
		if doc.syncing_status != "Failed":
			_prepare_copy(doc)
		result = start(
			doc.name, continuing=doc.syncing_status == "Failed", paired_peer=doc
		)
	return {"status": "In Progress", **result}


@frappe.whitelist(methods=["POST"])
def resume_slave():
	_fresh()
	from frappe.utils.synchronization import filelock

	with filelock("rms_slave_setup"):
		return _resume()


def finish_slave(doc, run):
	"""Runs inside the initial-copy transaction, before its successful final commit."""
	state = _state()
	if not state or state.connection != doc.name:
		return
	if doc.restaurant_branch != state.branch:
		frappe.throw(_("The linked branch does not match the selected Store."))
	store = frappe.get_doc("Store", state.store)
	if (
		not store.enabled
		or store.streaming_branch != state.branch
		or store.company != state.company
	):
		frappe.throw(_("The synchronized Store does not match this Slave setup."))
	company = frappe.get_doc("Company", store.company)
	from arab_streaming.streaming.connections import peer_state

	peer = peer_state(doc.doctype, doc.name)
	if not frappe.db.exists(
		"Streaming Record State",
		{
			"peer_state": peer.name,
			"reference_doctype": "Company",
			"remote_name": state.company,
		},
	):
		frappe.throw(
			_("The selected Company's full settings have not been synchronized yet.")
		)
	# Derive settings from the received company; never run ERPNext's company creator.
	frappe.db.set_single_value(
		"Global Defaults",
		{
			"default_company": company.name,
			"default_currency": company.default_currency,
			"country": company.country,
		},
	)
	frappe.db.set_single_value(
		"System Settings",
		{
			"country": company.country,
			"currency": company.default_currency,
			"language": frappe.db.get_single_value("System Settings", "language")
			or "en",
			"time_zone": frappe.db.get_single_value("System Settings", "time_zone")
			or "UTC",
		},
	)
	frappe.defaults.set_global_default("company", company.name)
	frappe.defaults.set_global_default("currency", company.default_currency)
	for app in frappe.get_all(
		"Installed Application", filters={"has_setup_wizard": 1}, pluck="app_name"
	):
		frappe.db.set_value(
			"Installed Application", {"app_name": app}, "is_setup_complete", 1
		)
	frappe.db.set_single_value("System Settings", "setup_complete", 1)
	frappe.db.set_default("desktop:home_page", "workspace")
	frappe.clear_cache()


def defer_initial_links(peer, document):
	from rms.setup_company import receiving_setup_company

	if peer.get("name") == _state().connection and receiving_setup_company():
		return {
			"Store": ["default_preparation_area", "pos_profile"],
			"Restaurant Brand": ["menus"],
		}.get(document.get("doctype"), [])
	return []


@frappe.whitelist(methods=["POST"])
def slave_status():
	_administrator()
	state = _state()
	if not state:
		return {"status": "Not Started"}
	doc = frappe.get_doc("Master Instance", state.connection)
	complete = doc.syncing_status == "Complete" and bool(frappe.is_setup_complete())
	return {
		"status": "Complete" if complete else doc.syncing_status,
		"progress": doc.progress or 0,
		"store": state.store,
		"branch": state.branch,
		"master_url": state.master_url,
		"error": doc.exceptions or doc.last_connection_exception,
		"connection_status": doc.connection_status,
		"setup_complete": complete,
	}
