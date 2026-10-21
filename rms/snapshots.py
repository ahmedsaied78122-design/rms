import json
from collections.abc import Mapping

import frappe
from frappe import _


def parse_json_rows(value):
	"""Load a JSON-backed child-row snapshot as attribute-accessible rows."""
	if not value:
		return []
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except (TypeError, json.JSONDecodeError):
			frappe.throw(_("POS Order contains invalid saved data."))
	if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
		frappe.throw(_("POS Order contains invalid saved data."))
	return [frappe._dict(row) for row in value]


def serialize_json_rows(rows):
	"""Serialize snapshot rows without losing Unicode or nested values."""
	if not rows:
		return "[]"
	if not isinstance(rows, (list, tuple)):
		frappe.throw(_("POS Order snapshot must contain a list of rows."))
	data = []
	for row in rows:
		as_dict = getattr(row, "as_dict", None)
		if callable(as_dict):
			row = as_dict()
		if not isinstance(row, Mapping):
			frappe.throw(_("POS Order snapshot contains an invalid row."))
		data.append(dict(row))
	return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
