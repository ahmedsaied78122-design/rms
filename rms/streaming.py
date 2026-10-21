"""Local, allowlisted RMS change journal. No remote transport is configured here."""

import hashlib
import json

import frappe


SYNC_SCHEMA_VERSION = 1

# Site-specific accounting, permissions, credentials, contacts, attachments, and
# ERPNext transactions are intentionally excluded from this first journal schema.
SYNC_SCHEMA = {
	"Store": {
		"fields": ["title", "store_code", "enabled", "operating_day_end", "default_preparation_area"],
		"children": {
			"brands": ("Store Brand Assignment", ["restaurant_brand", "is_default", "sequence_id"]),
			"working_hours": ("Store Working Hour", ["weekday", "from_time", "to_time", "order_type", "enabled"]),
		},
	},
	"Order Type": {"fields": ["title", "enabled", "sequence_id", "delivery_included", "require_table", "require_external_reference"]},
	"Preparation Area": {"fields": ["title", "store", "enabled", "sequence_id", "has_kds", "has_printer"]},
	"Dining Area": {"fields": ["title", "store", "restaurant_brand", "enabled", "sequence_id"]},
	"Dining Table": {"fields": ["title", "store", "dining_area", "capacity", "sequence_id", "enabled"]},
	"Restaurant Brand": {
		"fields": ["title", "brand_code", "enabled"],
		"children": {"menus": ("Brand Menu Assignment", ["store_menu", "sequence_id"])},
	},
	"Store Menu": {
		"fields": ["title", "restaurant_brand", "enabled"],
		"children": {"categories": ("Store Menu Category", ["product_category", "sequence_id"])},
	},
	"Product Category": {"fields": ["title", "parent_product_category", "sequence_id", "enabled", "is_group", "item_group", "default_preparation_area"]},
	"Modifier Group": {"fields": ["title", "enabled", "sequence_id", "allow_collapse", "collapsed_by_default"]},
	"Selling Product": {
		"fields": ["title", "item", "product_category", "uom", "maintain_stock", "enabled", "sequence_id", "is_modifier", "can_be_sold_separately", "has_options", "selling_price", "with_recipe", "default_store"],
		"children": {
			"option_products": ("Selling Product Option", ["option_product", "sequence_id"]),
			"selling_prices": ("Selling Product Price Rule", ["store", "order_type", "restaurant_brand", "selling_price", "priority"]),
			"recipe": ("Selling Product Recipe Line", ["item", "qty", "sub_recipe", "multi_level"]),
			"additional_recipe": ("Selling Product Additional Recipe Line", ["item", "qty", "order_types"]),
			"store_availability": ("Selling Product Store Availability", ["store"]),
			"store_order_type_exclusions": ("Selling Product Store Order Type Exclusion", ["store", "order_type"]),
			"modifier_groups": ("Selling Product Modifier Group", ["modifier_group", "sequence_id"]),
			"modifier_options": ("Selling Product Modifier Option", ["modifier_group", "modifier_product", "selling_price", "sequence_id"]),
			"print_routes": ("Selling Product Print Route", ["store", "preparation_area"]),
		},
	},
}

HOOKED_DOCTYPES = tuple(SYNC_SCHEMA)
SYNC_ACTIONS = {"insert", "update", "delete", "rename", "cancel"}


def _mapping(value):
	if isinstance(value, dict):
		return value
	to_dict = getattr(value, "as_dict", None)
	if callable(to_dict):
		return to_dict()
	return {}


def build_sync_payload(doctype, source, action="update", previous_name=None):
	"""Build a versioned snapshot with only the fields approved for this DocType."""
	if doctype not in SYNC_SCHEMA:
		raise ValueError(f"DocType is not on the RMS sync allowlist: {doctype}")
	if action not in SYNC_ACTIONS:
		raise ValueError(f"Unsupported RMS sync action: {action}")

	source = _mapping(source)
	source_name = source.get("name")
	if not source_name:
		raise ValueError("RMS sync events require a source document name")

	data = {}
	if action != "delete":
		schema = SYNC_SCHEMA[doctype]
		for fieldname in schema.get("fields", []):
			if fieldname in source:
				data[fieldname] = source[fieldname]
		for fieldname, (_child_doctype, child_fields) in schema.get("children", {}).items():
			if fieldname in source:
				data[fieldname] = [
					{key: row[key] for key in child_fields if key in row}
					for child in (source.get(fieldname) or [])
					if (row := _mapping(child)) and any(key in row for key in child_fields)
				]

	payload = {
		"schema_version": SYNC_SCHEMA_VERSION,
		"doctype": doctype,
		"name": source_name,
		"modified": source.get("modified"),
		"action": action,
		"data": data,
	}
	if previous_name and action == "rename":
		payload["previous_name"] = previous_name
	# Convert Frappe dates, times, and Decimals to stable JSON-safe values now.
	return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


def make_idempotency_key(site, doctype, name, modified, action, previous_name=None):
	parts = (site or "local", doctype, name, str(modified or ""), action, previous_name or "")
	return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def capture_doc_event(doc, method=None, *args):
	"""Journal an approved RMS master change only when local capture is enabled."""
	if doc.doctype not in SYNC_SCHEMA:
		return
	if not frappe.db.exists("DocType", "RMS Sync Settings"):
		return
	if not frappe.db.get_single_value("RMS Sync Settings", "capture_enabled"):
		return

	previous_name = None
	if method == "on_update":
		action = "insert" if doc.flags.in_insert else "update"
	elif method == "on_update_after_submit":
		action = "update"
	elif method == "on_trash":
		action = "delete"
	elif method == "on_cancel":
		action = "cancel"
	elif method == "after_rename":
		action = "rename"
		previous_name = args[0] if args else None
	else:
		return

	payload = build_sync_payload(doc.doctype, doc, action, previous_name)
	modified = doc.get("modified")
	idempotency_key = make_idempotency_key(
		getattr(frappe.local, "site", None), doc.doctype, payload["name"], modified, action, previous_name
	)
	if frappe.db.exists("RMS Sync Event", {"idempotency_key": idempotency_key}):
		return

	payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
	event = frappe.get_doc({
		"doctype": "RMS Sync Event",
		"source_doctype": doc.doctype,
		"source_name": payload["name"],
		"event_action": action,
		"schema_version": SYNC_SCHEMA_VERSION,
		"source_modified": modified,
		"idempotency_key": idempotency_key,
		"payload_hash": hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
		"payload": payload_json,
	})
	event.flags.from_streaming_capture = True
	event.insert(ignore_permissions=True, ignore_if_duplicate=True)


doc_events = {
	doctype: {
		"on_update": "rms.streaming.capture_doc_event",
		"on_update_after_submit": "rms.streaming.capture_doc_event",
		"on_trash": "rms.streaming.capture_doc_event",
		"on_cancel": "rms.streaming.capture_doc_event",
		"after_rename": "rms.streaming.capture_doc_event",
	}
	for doctype in HOOKED_DOCTYPES
}
