import math

import frappe
from frappe import _
from frappe.model.document import Document


def _limit(value):
	try:
		number = float(value)
	except (TypeError, ValueError):
		frappe.throw(_("Selection limits must be whole numbers zero or greater."))
	if not math.isfinite(number) or number < 0 or not number.is_integer():
		frappe.throw(_("Selection limits must be whole numbers zero or greater."))
	return int(number)


def get_minimum_selections(group_row, group_minimum=0):
	"""Read product-local rules; retain compatibility with rows predating migration."""
	requirement = group_row.get("selection_requirement") or "Default"
	if requirement not in ("Default", "Optional", "Required"):
		frappe.throw(_("Choose Default, Optional or Required for Selection Requirement."))
	if group_row.get("min_selections") is not None:
		return _limit(group_row.get("min_selections"))
	if requirement == "Optional":
		return 0
	if requirement == "Required":
		return 1
	return group_minimum or 0


def get_maximum_selections(group, group_row=None):
	"""Product-local zero means unlimited; old shared settings are migration fallback only."""
	if group_row is not None and group_row.get("max_selections") is not None:
		return _limit(group_row.get("max_selections"))
	return (group.get("max_selections") or 0) if group.get("allow_multiple_selections") else 1


def allows_multiple_selections(group, group_row):
	if group_row.get("max_selections") is not None:
		return get_maximum_selections(group, group_row) != 1
	return bool(group.get("allow_multiple_selections"))


def validate_product_limits(row):
	minimum = get_minimum_selections(row)
	maximum = get_maximum_selections({}, row)
	if maximum and maximum < minimum:
		frappe.throw(_("Maximum Selections cannot be lower than Minimum Selections."))
	return minimum, maximum


class SellingProductModifierGroup(Document):
	pass
