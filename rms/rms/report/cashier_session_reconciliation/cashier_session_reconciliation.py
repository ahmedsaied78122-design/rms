import frappe
from frappe import _
from frappe.utils import date_diff, getdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	roles = set(frappe.get_roles())
	if frappe.session.user == "Guest" or not (roles & {"POS Manager", "System Manager"}):
		frappe.throw(_("Only POS Managers can view cashier reconciliation."), frappe.PermissionError)
	if not filters.from_date or not filters.to_date:
		frappe.throw(_("Choose both a start and end date."))
	from_date, to_date = getdate(filters.from_date), getdate(filters.to_date)
	if from_date > to_date:
		frappe.throw(_("Start Date must be on or before End Date."))
	if date_diff(to_date, from_date) >= 90:
		frappe.throw(_("Choose a date range of 90 days or less."))

	conditions = ["cs.business_date between %(from_date)s and %(to_date)s"]
	values = {"from_date": from_date, "to_date": to_date, "user": frappe.session.user,
		"system_manager": int("System Manager" in roles)}
	if filters.store:
		frappe.get_doc("Store", filters.store)
		conditions.append("cs.store = %(store)s")
		values["store"] = filters.store
	if filters.cashier:
		conditions.append("cs.user = %(cashier)s")
		values["cashier"] = filters.cashier
	if filters.status:
		if filters.status not in ("Open", "Closing", "Closed"):
			frappe.throw(_("Choose a valid Cashier Session status."))
		conditions.append("cs.status = %(status)s")
		values["status"] = filters.status
	conditions.append("""(
		%(system_manager)s = 1
		OR NOT EXISTS (
			SELECT 1 FROM `tabStore User Assignment` scope_check
			WHERE scope_check.parent = cs.store AND scope_check.parenttype = 'Store' AND scope_check.enabled = 1
		)
		OR EXISTS (
			SELECT 1 FROM `tabStore User Assignment` scope_user
			WHERE scope_user.parent = cs.store AND scope_user.parenttype = 'Store'
				AND scope_user.enabled = 1 AND scope_user.user = %(user)s
		)
	)""")

	data = frappe.db.sql(
		f"""
		SELECT cs.name AS cashier_session, cs.business_date, cs.store, cs.user AS cashier,
			user.full_name AS cashier_name, cs.status AS session_status,
			cs.opened_at, cs.closed_at, company.default_currency AS currency,
			payment.mode_of_payment, payment.opening_amount, payment.expected_amount,
			payment.actual_amount, payment.difference
		FROM `tabCashier Session` cs
		INNER JOIN `tabCashier Session Payment` payment
			ON payment.parent = cs.name AND payment.parenttype = 'Cashier Session'
		LEFT JOIN `tabUser` user ON user.name = cs.user
		LEFT JOIN `tabCompany` company ON company.name = cs.store_company
		WHERE {' AND '.join(conditions)}
		ORDER BY cs.business_date DESC, cs.store, cs.user, cs.opened_at DESC, payment.idx
		""",
		values,
		as_dict=True,
	)

	columns = [
		{"fieldname": "cashier_session", "label": _("Cashier Session"), "fieldtype": "Link", "options": "Cashier Session", "width": 175},
		{"fieldname": "business_date", "label": _("Business Date"), "fieldtype": "Date", "width": 105},
		{"fieldname": "store", "label": _("Store"), "fieldtype": "Link", "options": "Store", "width": 135},
		{"fieldname": "cashier_name", "label": _("Cashier"), "fieldtype": "Data", "width": 150},
		{"fieldname": "session_status", "label": _("Status"), "fieldtype": "Data", "width": 95},
		{"fieldname": "opened_at", "label": _("Opened At"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "closed_at", "label": _("Closed At"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "mode_of_payment", "label": _("Mode of Payment"), "fieldtype": "Link", "options": "Mode of Payment", "width": 145},
		{"fieldname": "opening_amount", "label": _("Opening Amount"), "fieldtype": "Currency", "options": "currency", "width": 125},
		{"fieldname": "expected_amount", "label": _("Expected Amount"), "fieldtype": "Currency", "options": "currency", "width": 125},
		{"fieldname": "actual_amount", "label": _("Actual Amount"), "fieldtype": "Currency", "options": "currency", "width": 125},
		{"fieldname": "difference", "label": _("Difference"), "fieldtype": "Currency", "options": "currency", "width": 125},
		{"fieldname": "currency", "label": _("Currency"), "fieldtype": "Link", "options": "Currency", "width": 90},
	]
	return columns, data
