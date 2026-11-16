import unittest
from unittest.mock import patch
from inspect import unwrap

import frappe
from rms.form_queries import scoped_link

# Native sanitizer is tested by Frappe; exercise permission-aware query composition here.
query = unwrap(scoped_link)


class TestRMSFormQueries(unittest.TestCase):
	def run_query(self, dt="Restaurant Brand", **filters):
		return query(dt, "", "name", 0, 20, filters)

	def test_empty_scope_cannot_expose_global_records(self):
		with patch("frappe.get_list") as get_list, patch("frappe.get_all") as get_all:
			self.assertEqual(self.run_query(stores=[]), [])
			self.assertFalse(any(call.args and call.args[0] in {"Store","User","Restaurant Brand","Order Type","Preparation Area","POS Profile"} for call in get_list.call_args_list))
			get_all.assert_not_called()

	def test_only_permission_filtered_stores_can_supply_child_scope(self):
		with patch("frappe.get_list", side_effect=[
			[frappe._dict(name="VISIBLE", company="C1")], [frappe._dict(name="Brand A")],
		]) as get_list, patch("frappe.get_all", return_value=["Brand A"]) as children:
			self.assertEqual(self.run_query(stores=["VISIBLE", "INACCESSIBLE"]), [["Brand A"]])
			self.assertEqual(children.call_args.kwargs["filters"]["parent"], ["in", ["VISIBLE"]])
			self.assertEqual(get_list.call_args_list[-1].args[0], "Restaurant Brand")
			self.assertEqual(get_list.call_args_list[-1].kwargs["filters"]["enabled"], 1)

	def test_pos_profile_company_comes_from_visible_store(self):
		with patch("frappe.get_list", side_effect=[
			[frappe._dict(name="A", company="Allowed Company")], [],
		]) as get_list:
			self.run_query("POS Profile", stores=["A"], company="Injected")
			self.assertEqual(get_list.call_args.kwargs["filters"], {"disabled":0,"company":["in",["Allowed Company"]]})

	def test_preparation_area_is_scoped_to_store_and_kitchen(self):
		with patch("frappe.get_list", side_effect=[[frappe._dict(name="A", company="C")], []]) as get_list:
			self.run_query("Preparation Area", stores=["A"], kds_only=1)
			self.assertEqual(get_list.call_args.kwargs["filters"], {"enabled":1,"store":["in",["A"]],"has_kds":1})

	def test_no_visible_stores_does_not_query_child_records(self):
		with patch("frappe.get_list", return_value=[]), patch("frappe.get_all") as children:
			self.assertEqual(self.run_query(stores=["PRIVATE"]), [])
			children.assert_not_called()

	def test_arbitrary_doctypes_and_malformed_scopes_are_rejected(self):
		with patch("frappe.get_list") as get_list:
			with self.assertRaises(frappe.PermissionError): self.run_query("User", stores=["A"])
			with self.assertRaises(frappe.ValidationError): self.run_query(stores="A")
			with self.assertRaises(frappe.ValidationError): self.run_query(stores=["A"]*201)
			self.assertFalse(any(call.args and call.args[0] in {"Store","User","Restaurant Brand","Order Type","Preparation Area","POS Profile"} for call in get_list.call_args_list))
