import unittest
from unittest.mock import Mock, patch

import frappe

from rms.api.printing import (
	get_print_dispatch_job_permission_query,
	get_print_dispatch_jobs,
	has_print_dispatch_job_permission,
	render_ticket,
	retry_print_job,
)


class TestPrintDispatchManagement(unittest.TestCase):
	def test_item_cancellation_receipt_identifies_its_table_order(self):
		job = frappe._dict(
			document_type="Kitchen Ticket",
			document_name="RMS-KT-2026-00028",
			store="Zamalek Riverside Kitchen",
			preparation_area="Beverage Counter",
			payload="CANCEL 1 × Mint Lemonade: customer cancelled one cup",
		)
		ticket = frappe._dict(name=job.document_name, pos_order="RMS-ORD-2026-00027")
		order = frappe._dict(name=ticket.pos_order, order_type="Dine In", dining_table="Table 03")
		with patch("frappe.db.get_value", side_effect=["Zamalek Riverside Kitchen", "Beverage Counter"]), \
				patch("frappe.get_doc", side_effect=[ticket, order]):
			receipt = render_ticket(job).decode("utf-8")

		self.assertIn("RMS-ORD-2026-00027", receipt)
		self.assertIn("Dine In · Table 03", receipt)
		self.assertIn("CANCEL 1 × Mint Lemonade: customer cancelled one cup", receipt)

	def test_cashier_cannot_read_print_dispatch_queue(self):
		with patch("frappe.get_roles", return_value=["POS Cashier"]), \
				patch("frappe.session", frappe._dict(user="cashier@example.com")):
			with self.assertRaises(frappe.PermissionError):
				get_print_dispatch_jobs()

	def test_manager_can_list_jobs_for_an_accessible_store(self):
		rows = [frappe._dict(name="RMS-PRINT-1", store="STORE-1", status="Failed")]
		with patch("frappe.get_roles", return_value=["POS Manager"]), \
				patch("frappe.session", frappe._dict(user="manager@example.com")), \
				patch("rms.api.printing._user_has_store_access", return_value=True), \
				patch("frappe.get_list", return_value=rows) as get_list:
			result = get_print_dispatch_jobs(store="STORE-1", status="Failed")
		self.assertEqual(result, rows)
		self.assertEqual(get_list.call_args.kwargs["filters"], {"store": "STORE-1", "status": "Failed"})
		self.assertEqual(get_list.call_args.kwargs["limit_page_length"], 100)

	def test_manager_cannot_request_jobs_for_an_unassigned_store(self):
		with patch("frappe.get_roles", return_value=["POS Manager"]), \
				patch("frappe.session", frappe._dict(user="manager@example.com")), \
				patch("rms.api.printing._user_has_store_access", return_value=False), \
				patch("frappe.get_list") as get_list:
			with self.assertRaises(frappe.PermissionError):
				get_print_dispatch_jobs(store="STORE-OTHER")
		get_list.assert_not_called()

	def test_manager_can_retry_failed_job_only_in_an_assigned_store(self):
		job = frappe._dict(name="RMS-PRINT-1", store="STORE-1", status="Failed", retry=Mock())
		job.retry.side_effect = lambda: setattr(job, "status", "Queued")
		with patch("frappe.get_roles", return_value=["POS Manager"]), \
				patch("frappe.session", frappe._dict(user="manager@example.com")), \
				patch("rms.api.printing._user_has_store_access", return_value=True), \
				patch("frappe.get_doc", return_value=job):
			result = retry_print_job("RMS-PRINT-1")
			job.retry.assert_called_once_with()
			self.assertEqual(result["status"], "Queued")

	def test_manager_cannot_retry_job_in_an_unassigned_store(self):
		job = frappe._dict(name="RMS-PRINT-1", store="STORE-OTHER", status="Failed", retry=Mock())
		with patch("frappe.get_roles", return_value=["POS Manager"]), \
				patch("frappe.session", frappe._dict(user="manager@example.com")), \
				patch("rms.api.printing._user_has_store_access", return_value=False), \
				patch("frappe.get_doc", return_value=job):
			with self.assertRaises(frappe.PermissionError):
				retry_print_job("RMS-PRINT-1")
		job.retry.assert_not_called()

	def test_manager_list_permission_query_is_limited_to_assigned_stores(self):
		with patch("frappe.get_roles", return_value=["POS Manager"]), \
				patch("frappe.db.get_value", return_value="POS-USER-1"), \
				patch("frappe.db.escape", return_value="'manager@example.com'"):
			condition = get_print_dispatch_job_permission_query("manager@example.com")
		self.assertIn("`tabPrint Dispatch Job`.store in", condition)
		self.assertIn("tabPOS User Store", condition)
		self.assertIn("pu.enabled = 1", condition)

	def test_print_job_read_permission_is_store_scoped(self):
		job = frappe._dict(store="STORE-1")
		with patch("frappe.get_roles", return_value=["POS Manager"]), \
				patch("rms.api.printing._user_has_store_access", return_value=False):
			self.assertFalse(has_print_dispatch_job_permission(job, "manager@example.com", "read"))
