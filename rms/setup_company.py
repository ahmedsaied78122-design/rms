"""Preserve source accounts during first-run slave bootstrap only."""

from contextlib import contextmanager
from contextvars import ContextVar

import frappe
from erpnext.accounts.doctype.account.account import Account
from erpnext.accounts.doctype.cost_center.cost_center import CostCenter
from erpnext.setup.doctype.company.company import Company
from frappe.utils.nestedset import NestedSet

_scaffolding = ContextVar("rms_company_scaffolding", default=False)


@contextmanager
def scaffolding():
	token = _scaffolding.set(True)
	try:
		yield
	finally:
		_scaffolding.reset(token)


def receiving_setup_company():
	from arab_streaming.streaming.context import replay_source

	source = replay_source()
	state = frappe.conf.get("rms_slave_setup") or {}
	return bool(
		source
		and state.get("connection")
		and frappe.conf.get("arab_streaming_site_role") == "Slave"
		and not frappe.is_setup_complete()
		and frappe.db.exists(
			"Streaming Peer State",
			{
				"instance_type": "Master Instance",
				"instance_name": state["connection"],
				"pairing_id": source,
			},
		)
	)


class RMSSetupCompany(Company):
	def on_update(self):
		if _scaffolding.get() or receiving_setup_company():
			# Normal Company validation still runs. Accounts, warehouses and defaults
			# are received from the master rather than generated from a local template.
			return NestedSet.on_update(self)
		return super().on_update()


class RMSSetupAccount(Account):
	def _get_missing_mandatory_fields(self):
		missing = super()._get_missing_mandatory_fields()
		if (
			self.is_new()
			and self.is_group
			and not self.parent_account
			and self.root_type in ("Asset", "Liability", "Income", "Expense", "Equity")
			and receiving_setup_company()
		):
			# ERPNext's chart installer also allows parentless root groups. Keep every
			# other mandatory field and all Account controller validation intact.
			return [item for item in missing if item[0] != "parent_account"]
		return missing


class RMSSetupCostCenter(CostCenter):
	def _get_missing_mandatory_fields(self):
		missing = super()._get_missing_mandatory_fields()
		if (
			self.is_new()
			and self.is_group
			and not self.parent_cost_center
			and self.cost_center_name == self.company
			and receiving_setup_company()
		):
			return [item for item in missing if item[0] != "parent_cost_center"]
		return missing
