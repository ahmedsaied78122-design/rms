import secrets

import frappe
from frappe import _
from frappe.utils import add_to_date, flt, now_datetime
from frappe.utils.password import passlibctx

from rms.api.pos import assert_store_access, get_active_pos_user, get_user_session, require_pos_role


EXPENSE_APPROVAL_ACTION = "Post Shift Expense"
APPROVAL_CODE_MINUTES = 3


def get_expense_context():
	require_pos_role()
	session = get_user_session()
	if not session or session.status != "Open":
		frappe.throw(_("Open a cashier session before recording an expense."))
	store = assert_store_access(session.store)
	categories = frappe.get_all(
		"Expense Category",
		filters={"company": store.company, "enabled": 1},
		fields=["name", "title"],
		order_by="title asc",
	)
	pending = frappe.get_all(
		"Shift Expense",
		filters={"cashier_session": session.name, "owner": frappe.session.user, "status": "Pending Approval"},
		fields=["name", "expense_category", "amount", "mode_of_payment", "creation"],
		order_by="creation desc",
	)
	return {"company": store.company, "currency": frappe.db.get_value("Company", store.company, "default_currency"),
		"categories": categories, "pending_expenses": pending}


def get_manager_pending_shift_expenses():
	"""Return Store-scoped pending expenses for manager actions inside POS."""
	require_pos_role()
	if not (set(frappe.get_roles(frappe.session.user)) & {"POS Manager", "System Manager"}):
		frappe.throw(_("Only a POS Manager can review pending expenses."), frappe.PermissionError)

	rows = frappe.get_list(
		"Shift Expense",
		filters={"status": "Pending Approval", "owner": ["!=", frappe.session.user]},
		fields=["name", "store", "cashier", "expense_category", "amount", "currency", "mode_of_payment", "creation"],
		order_by="creation asc",
		limit_page_length=100,
	)
	users = list({row.cashier for row in rows if row.cashier})
	full_names = {row.name: row.full_name for row in frappe.get_all(
		"User", filters={"name": ["in", users]}, fields=["name", "full_name"]
	)} if users else {}
	for row in rows:
		row["cashier_full_name"] = full_names.get(row.cashier) or row.cashier
		row.pop("cashier", None)
	return rows


def _get_expense_payment_account(company, mode_of_payment):
	account = frappe.db.get_value("Mode of Payment Account", {
		"parent": mode_of_payment, "parenttype": "Mode of Payment", "company": company,
	}, "default_account")
	if not account:
		frappe.throw(_("Set a company-specific Default Account on Mode of Payment {0} before using it for POS expenses.").format(mode_of_payment))
	info = frappe.db.get_value("Account", account,
		["company", "root_type", "account_type", "is_group", "account_currency"], as_dict=True)
	currency = frappe.db.get_value("Company", company, "default_currency")
	if (not info or info.company != company or info.root_type != "Asset" or info.is_group
			or info.account_type not in ("Cash", "Bank") or info.account_currency != currency):
		frappe.throw(_("The Mode of Payment account must be a non-group Cash or Bank account in the Company currency."))
	return account


def _can_post_expense_directly(user):
	roles = set(frappe.get_roles(user))
	if roles & {"POS Manager", "System Manager"}:
		return True
	pos_user = get_active_pos_user(user)
	return bool(pos_user and frappe.db.get_value("POS User", pos_user, "can_payout"))


def _get_open_expense_session(lock=False):
	require_pos_role()
	session = get_user_session()
	if not session:
		frappe.throw(_("An Open Cashier Session is required for POS expenses."))
	if lock:
		frappe.db.sql("select name from `tabCashier Session` where name = %s for update", session.name)
		session.reload()
	if session.status != "Open":
		frappe.throw(_("An Open Cashier Session is required for POS expenses."))
	assert_store_access(session.store)
	return session


@frappe.whitelist()
def create_shift_expense(expense_category, amount, mode_of_payment, remarks=None, attachment=None):
	session = _get_open_expense_session(lock=True)
	amount = flt(amount, precision=frappe.get_precision("Shift Expense", "amount") or 2)
	if amount <= 0:
		frappe.throw(_("Enter an expense amount greater than zero."))
	if mode_of_payment not in {row.mode_of_payment for row in session.payments}:
		frappe.throw(_("Choose a Mode of Payment configured for the open Cashier Session."))
	category = frappe.db.get_value("Expense Category", expense_category,
		["enabled", "company", "expense_account", "cost_center"], as_dict=True)
	company = frappe.db.get_value("Store", session.store, "company")
	if not category or not category.enabled or category.company != company:
		frappe.throw(_("Choose an enabled Expense Category for this Store's Company."))
	expense_account = frappe.db.get_value("Account", category.expense_account,
		["company", "root_type", "is_group", "account_currency"], as_dict=True)
	company_currency = frappe.db.get_value("Company", company, "default_currency")
	if (not expense_account or expense_account.company != company or expense_account.root_type != "Expense"
			or expense_account.is_group or expense_account.account_currency != company_currency):
		frappe.throw(_("The Expense Category must map to a valid Expense Account in the Company currency."))
	if category.cost_center:
		cost_center = frappe.db.get_value("Cost Center", category.cost_center,
			["company", "is_group"], as_dict=True)
		if not cost_center or cost_center.company != company or cost_center.is_group:
			frappe.throw(_("The Expense Category must map to an active Cost Center in the Store's Company."))
	payment_account = _get_expense_payment_account(company, mode_of_payment)
	if attachment and frappe.db.get_value("File", {"file_url": attachment}, "owner") != frappe.session.user:
		frappe.throw(_("Attach a receipt uploaded by your User."), frappe.PermissionError)
	can_post = _can_post_expense_directly(frappe.session.user)
	doc = frappe.new_doc("Shift Expense")
	doc.update({
		"cashier_session": session.name,
		"store": session.store,
		"company": company,
		"cashier": session.user,
		"business_date": session.business_date,
		"currency": company_currency,
		"expense_category": expense_category,
		"expense_account": category.expense_account,
		"cost_center": category.cost_center,
		"mode_of_payment": mode_of_payment,
		"payment_account": payment_account,
		"amount": amount,
		"remarks": remarks,
		"attachment": attachment,
		"status": "Draft" if can_post else "Pending Approval",
	})
	doc.flags.from_pos_api = True
	doc.insert(ignore_permissions=True)
	if can_post:
		doc.post_to_ledger(frappe.session.user)
	return {"name": doc.name, "status": doc.status, "journal_entry": doc.journal_entry,
		"requires_approval": doc.status == "Pending Approval"}


@frappe.whitelist()
def issue_shift_expense_approval_code(expense_name):
	if not (set(frappe.get_roles(frappe.session.user)) & {"POS Manager", "System Manager"}):
		frappe.throw(_("Only a POS Manager can issue an expense approval code."), frappe.PermissionError)
	doc = frappe.get_doc("Shift Expense", expense_name)
	assert_store_access(doc.store)
	if doc.status != "Pending Approval":
		frappe.throw(_("Only a pending Shift Expense can be approved."))
	if doc.owner == frappe.session.user:
		frappe.throw(_("A different User must approve this expense."), frappe.PermissionError)
	for row in frappe.get_all("Approval Challenge", filters={
		"subject_doctype": "Shift Expense", "subject_name": doc.name,
		"action": EXPENSE_APPROVAL_ACTION, "status": "Issued",
	}, fields=["name"]):
		challenge = frappe.get_doc("Approval Challenge", row.name)
		challenge.status = "Revoked"
		challenge.flags.from_pos_api = True
		challenge.save(ignore_permissions=True)
	code = f"{secrets.randbelow(1_000_000):06d}"
	challenge = frappe.new_doc("Approval Challenge")
	challenge.update({
		"store": doc.store,
		"subject_doctype": "Shift Expense",
		"subject_name": doc.name,
		"action": EXPENSE_APPROVAL_ACTION,
		"requester": doc.owner,
		"approver": frappe.session.user,
		"status": "Issued",
		"code_hash": passlibctx.hash(code),
		"expires_at": add_to_date(now_datetime(), minutes=APPROVAL_CODE_MINUTES),
	})
	challenge.flags.from_pos_api = True
	challenge.insert(ignore_permissions=True)
	return {"challenge": challenge.name, "code": code, "expires_at": challenge.expires_at}


@frappe.whitelist()
def redeem_shift_expense_approval_code(expense_name, code):
	session = _get_open_expense_session(lock=True)
	doc = frappe.get_doc("Shift Expense", expense_name)
	if doc.owner != frappe.session.user or doc.cashier_session != session.name:
		frappe.throw(_("This expense does not belong to your open Cashier Session."), frappe.PermissionError)
	if doc.status != "Pending Approval":
		frappe.throw(_("Only a pending Shift Expense can be approved."))
	names = frappe.get_all("Approval Challenge", filters={
		"subject_doctype": "Shift Expense",
		"subject_name": doc.name,
		"action": EXPENSE_APPROVAL_ACTION,
		"requester": doc.owner,
		"status": "Issued",
		"expires_at": [">", now_datetime()],
	}, fields=["name"], order_by="creation desc", limit=1)
	if not names:
		frappe.throw(_("Ask a POS Manager to issue a current approval code."))
	challenge_name = names[0].name
	frappe.db.sql("select name from `tabApproval Challenge` where name = %s for update", challenge_name)
	challenge = frappe.get_doc("Approval Challenge", challenge_name)
	challenge.verify_code(code)
	doc.post_to_ledger(challenge.approver)
	return {"name": doc.name, "status": doc.status, "journal_entry": doc.journal_entry}


@frappe.whitelist()
def reject_shift_expense(expense_name, reason):
	if not (set(frappe.get_roles(frappe.session.user)) & {"POS Manager", "System Manager"}):
		frappe.throw(_("Only a POS Manager can reject a Shift Expense."), frappe.PermissionError)
	doc = frappe.get_doc("Shift Expense", expense_name)
	assert_store_access(doc.store)
	if doc.status != "Pending Approval":
		frappe.throw(_("Only a pending Shift Expense can be rejected."))
	if not str(reason or "").strip():
		frappe.throw(_("Enter a reason when rejecting an expense."))
	doc.status = "Rejected"
	doc.rejected_by = frappe.session.user
	doc.rejected_at = now_datetime()
	doc.rejection_reason = str(reason).strip()[:2000]
	doc.flags.from_pos_api = True
	doc.save(ignore_permissions=True)
	for row in frappe.get_all("Approval Challenge", filters={
		"subject_doctype": "Shift Expense", "subject_name": doc.name,
		"action": EXPENSE_APPROVAL_ACTION, "status": "Issued",
	}, fields=["name"]):
		challenge = frappe.get_doc("Approval Challenge", row.name)
		challenge.status = "Revoked"
		challenge.flags.from_pos_api = True
		challenge.save(ignore_permissions=True)
	return {"name": doc.name, "status": doc.status}
