import frappe
from frappe import _
from frappe.model.naming import getseries
from frappe.utils import getdate, nowdate


def _next_order_sequence(prefix):
	# Seed without a locking read of a missing key. Different branches can start
	# their daily counters concurrently without competing gap locks in tabSeries.
	frappe.db.multisql({
		"mariadb": "INSERT INTO `tabSeries` (`name`, `current`) VALUES (%s, 0) "
			"ON DUPLICATE KEY UPDATE `current` = `current`",
		"postgres": 'INSERT INTO "tabSeries" ("name", "current") VALUES (%s, 0) '
			'ON CONFLICT ("name") DO NOTHING',
	}, (prefix,))
	return getseries(prefix, 4)


def next_pos_order_name(store):
	"""Allocate a daily number scoped to a Store's unique code."""
	code = (frappe.db.get_value("Store", store, "store_code", for_update=True) or "").strip().lower()
	if not code:
		frappe.throw(_("Set a Store Code before creating an order."))
	prefix = f"{code}-{getdate(nowdate()).strftime('%d%m%Y')}-"
	return prefix + _next_order_sequence(prefix), prefix
