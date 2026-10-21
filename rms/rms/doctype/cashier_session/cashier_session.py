import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from rms.utils import get_business_date


class CashierSession(Document):
	def before_insert(self):
		self.user = self.user or frappe.session.user
		self.load_store_defaults()
		self.status = "Open"
		self.opened_at = now_datetime()
		self.business_date = get_business_date(self.store)
		self.load_payment_methods()

	def validate(self):
		self.validate_context()
		self.validate_open_session()
		self.validate_payments()
		self.update_expected_amounts()
		self.validate_status_change()

	def load_store_defaults(self):
		if not self.store:
			frappe.throw(_("Select a Store before opening a cashier session."))
		store = frappe.get_doc("Store", self.store)
		if not store.enabled:
			frappe.throw(_("The selected Store is disabled."))
		if not self.pos_profile:
			from rms.api.pos import get_pos_profile_for_store

			self.pos_profile = get_pos_profile_for_store(self.store, self.user) or store.pos_profile
		if not self.pos_profile:
			frappe.throw(_("Set a POS Profile on the Store or assign one to this POS User."))

	def load_payment_methods(self):
		if self.payments:
			return
		profile = frappe.get_doc("POS Profile", self.pos_profile)
		for method in profile.payments:
			self.append(
				"payments",
				{
					"mode_of_payment": method.mode_of_payment,
					"opening_amount": 0,
					"expected_amount": 0,
				},
			)
		if not self.payments:
			frappe.throw(_("Add at least one payment method to the Store POS Profile."))

	def validate_context(self):
		store = frappe.db.get_value("Store", self.store, ["company", "pos_profile", "enabled"], as_dict=True)
		if not store or not store.enabled:
			frappe.throw(_("Choose an enabled Store."))
		from rms.api.pos import get_active_pos_user

		pos_user = get_active_pos_user(self.user)
		assigned_profile = frappe.db.get_value("POS User Store", {
			"parent": pos_user, "parenttype": "POS User", "store": self.store,
		}, "pos_profile") if pos_user else None
		if assigned_profile and self.pos_profile != assigned_profile:
			frappe.throw(_("Use the Cashier POS Profile assigned to this POS User and Store."))
		if not assigned_profile and store.pos_profile and self.pos_profile != store.pos_profile:
			frappe.throw(_("Use the POS Profile assigned to this Store or assign a cashier-specific POS Profile."))
		profile = frappe.db.get_value("POS Profile", self.pos_profile, ["company", "disabled"], as_dict=True)
		if not profile or profile.disabled or profile.company != store.company:
			frappe.throw(_("POS Profile must be enabled and belong to the Store Company."))
		if not self.pos_opening_entry:
			frappe.throw(_("Create the standard ERPNext POS Opening Entry before opening a Cashier Session."))
		opening = frappe.db.get_value("POS Opening Entry", self.pos_opening_entry,
			["company", "pos_profile", "user", "status"], as_dict=True)
		if (not opening or opening.company != store.company or opening.pos_profile != self.pos_profile
				or opening.user != self.user or (self.status == "Open" and opening.status != "Open")
				or (self.status in ("Closing", "Closed") and opening.status not in ("Open", "Closed"))):
			frappe.throw(_("The linked ERPNext POS Opening Entry must match the Store, POS Profile, and cashier, and remain in a valid status."))
		if not frappe.db.get_value("User", self.user, "enabled"):
			frappe.throw(_("The selected cashier User is disabled."))

		if pos_user:
			if not frappe.db.exists("POS User Store", {
				"parent": pos_user, "parenttype": "POS User", "store": self.store,
			}):
				frappe.throw(_("This POS User is not assigned to the selected Store."))
		else:
			allowed_users = frappe.get_all(
				"Store User Assignment",
				filters={"parent": self.store, "parenttype": "Store", "enabled": 1},
				pluck="user",
			)
			if allowed_users and self.user not in allowed_users:
				frappe.throw(_("This User is not allowed to open a session for the Store."))

	def validate_open_session(self):
		if self.status not in ("Open", "Closing"):
			return
		filters = {"user": self.user, "status": ["in", ["Open", "Closing"]]}
		if self.name:
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("Cashier Session", filters):
			frappe.throw(_("This cashier already has an open session. Close it before opening another."))

	def validate_payments(self):
		configured = {
			row.mode_of_payment
			for row in frappe.get_all(
				"POS Payment Method",
				filters={"parent": self.pos_profile, "parenttype": "POS Profile"},
				fields=["mode_of_payment"],
			)
		}
		seen = set()
		for row in self.payments:
			if row.mode_of_payment in seen:
				frappe.throw(_("Each Mode of Payment can only appear once in the session."))
			seen.add(row.mode_of_payment)
			if row.mode_of_payment not in configured:
				frappe.throw(_("Mode of Payment {0} is not configured on the POS Profile.").format(row.mode_of_payment))
			# Empty Currency values can round-trip from MariaDB as 0 before closing.
			if row.actual_amount is not None and flt(row.actual_amount) != 0 and self.status not in ("Closing", "Closed"):
				frappe.throw(_("Actual amounts can only be entered while closing the session."))
		if configured != seen:
			frappe.throw(_("The session must retain all payment methods from its POS Profile."))

	def update_expected_amounts(self):
		paid_orders = frappe.get_all(
			"POS Order", filters={"cashier_session": self.name, "status": "Paid"}, pluck="name"
		)
		paid_by_method = {}
		if paid_orders:
			for payment in frappe.get_all(
				"POS Order Payment",
				filters={"parent": ["in", paid_orders], "parenttype": "POS Order"},
				fields=["mode_of_payment", "amount"],
			):
				paid_by_method[payment.mode_of_payment] = (
					paid_by_method.get(payment.mode_of_payment, 0) + (payment.amount or 0)
				)
		refunds = frappe.get_all("POS Return Payment", filters={
			"parenttype": "POS Return", "parent": ["in", frappe.get_all("POS Return", filters={
				"cashier_session": self.name, "status": "Approved", "docstatus": ["<", 2]
			}, pluck="name") or ["__none__"]],
		}, fields=["mode_of_payment", "amount"])
		for payment in refunds:
			paid_by_method[payment.mode_of_payment] = paid_by_method.get(payment.mode_of_payment, 0) - payment.amount

		for expense in frappe.get_all(
			"Shift Expense",
			filters={"cashier_session": self.name, "status": "Posted"},
			fields=["mode_of_payment", "amount"],
		):
			paid_by_method[expense.mode_of_payment] = (
				paid_by_method.get(expense.mode_of_payment, 0) - (expense.amount or 0)
			)

		for row in self.payments:
			row.expected_amount = (row.opening_amount or 0) + paid_by_method.get(row.mode_of_payment, 0)
			row.difference = (
				(row.actual_amount or 0) - row.expected_amount
				if self.status in ("Closing", "Closed") and row.actual_amount is not None else 0
			)

	def validate_status_change(self):
		previous = self.get_doc_before_save()
		if not previous:
			if self.status != "Open":
				frappe.throw(_("A new Cashier Session must start Open."))
			return

		if previous.status == "Closed" and self.status != "Closed":
			frappe.throw(_("A closed Cashier Session cannot be reopened."))
		if previous.status == "Open" and self.status not in ("Open", "Closing"):
			frappe.throw(_("Use the session close workflow to change its status."))
		if previous.status == "Closing" and self.status not in ("Closing", "Closed"):
			frappe.throw(_("A session being closed cannot return to Open."))

		if self.status == "Closed":
			if not self.pos_opening_entry or not self.pos_closing_entry:
				frappe.throw(_("Link the standard ERPNext POS Opening and Closing Entries before closing the session."))
			if frappe.db.get_value("POS Opening Entry", self.pos_opening_entry, "status") != "Closed":
				frappe.throw(_("The ERPNext POS Closing Entry has not completed invoice consolidation yet."))
			if frappe.db.get_value("POS Closing Entry", self.pos_closing_entry, "status") != "Submitted":
				frappe.throw(_("The ERPNext POS Closing Entry must be successfully submitted before closing the session."))
			if any(row.actual_amount is None for row in self.payments):
				frappe.throw(_("Enter an Actual Amount for every payment method before closing."))
			if frappe.db.exists(
				"POS Order",
				{
					"cashier_session": self.name,
					"status": ["not in", ["Paid", "Cancelled"]],
				},
			):
				frappe.throw(_("Finish or cancel every open order before closing the session."))
			if frappe.db.exists("POS Return", {"cashier_session": self.name, "status": "Pending Approval", "docstatus": ["<", 2]}):
				frappe.throw(_("Approve or reject every pending POS Return before closing the session."))
			if frappe.db.exists("Shift Expense", {"cashier_session": self.name, "status": "Pending Approval"}):
				frappe.throw(_("Approve or reject every pending Shift Expense before closing the session."))
			if not self.closed_at:
				self.closed_at = now_datetime()

	def begin_closing(self):
		frappe.db.sql("select name from `tabCashier Session` where name = %s for update", self.name)
		self.reload()
		if self.status != "Open":
			frappe.throw(_("Only an Open session can begin closing."))
		if frappe.db.exists(
			"POS Order",
			{
				"cashier_session": self.name,
				"status": ["not in", ["Paid", "Cancelled"]],
			},
		):
			frappe.throw(_("Finish or cancel all orders before beginning session close."))
		if frappe.db.exists("POS Return", {"cashier_session": self.name, "status": "Pending Approval", "docstatus": ["<", 2]}):
			frappe.throw(_("Approve or reject every pending POS Return before beginning session close."))
		if frappe.db.exists("Shift Expense", {"cashier_session": self.name, "status": "Pending Approval"}):
			frappe.throw(_("Approve or reject every pending Shift Expense before beginning session close."))
		self.status = "Closing"
		self.save(ignore_permissions=True)

	def finish_closing(self):
		if self.status != "Closing":
			frappe.throw(_("The session must be in Closing status."))
		self.status = "Closed"
		self.save(ignore_permissions=True)
