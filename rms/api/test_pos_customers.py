import json
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from rms.api.pos import create_customer, get_customer_details, save_customer_details, update_customer


class TestPOSCustomers(unittest.TestCase):
	def setUp(self):
		stack = ExitStack()
		self.addCleanup(stack.close)
		def throw(message, exc=frappe.ValidationError):
			raise exc(message)
		for target, kwargs in (
			("require_pos_role", {}),
			("assert_store_access", {}),
			("get_pos_profile_for_store", {"return_value": "PROFILE-1"}),
			("frappe.db", {"new": MagicMock(), "create": True}),
			("frappe.get_doc", {}),
			("frappe.throw", {"side_effect": throw}),
			("_", {"side_effect": lambda message: message}),
		):
			mock = stack.enter_context(patch(f"rms.api.pos.{target}", **kwargs))
			if target == "frappe.db":
				self.db = mock
			elif target == "frappe.get_doc":
				self.get_doc = mock
		self.db.get_value.side_effect = lambda doctype, *args, **kwargs: {
			"POS Profile": "DEFAULT-CUSTOMER",
			"Customer": {"customer_group": "Individual", "territory": "Egypt"},
			"Store": "COMPANY-1",
			"Company": "Egypt",
		}.get(doctype)
		self.customer = MagicMock()
		self.customer.name = "CUSTOMER-1"
		self.customer.customer_name = "AHMED"
		self.customer.mobile_no = "02344324"
		self.customer.customer_primary_address = None
		self.customer.customer_primary_contact = "CONTACT-1"
		self.customer.disabled = 0
		self.get_doc.return_value = self.customer

	def create_customer(self, **kwargs):
		return create_customer("AHMED", "02344324", "STORE-1", **kwargs)

	def test_customer_without_address_accepts_empty_form_and_json_values(self):
		for address in (None, "", "  \t ", "null", {}, "{}"):
			with self.subTest(address=address):
				self.get_doc.reset_mock()
				result = self.create_customer(address=address, additional_phones="[]")
				self.assertEqual(result, {"name": "CUSTOMER-1", "customer_name": "AHMED",
					"mobile_no": "02344324"})
				self.get_doc.assert_called_once()
				self.customer.insert.assert_called_with(ignore_permissions=True)

	def test_empty_optional_phone_values_are_accepted(self):
		for phones in (None, "", "  ", "null", [], "[]"):
			with self.subTest(phones=phones):
				self.create_customer(additional_phones=phones, address="")

	def test_valid_address_is_created_and_linked(self):
		address = {"address_line1": "  Street 1 ", "city": " Cairo "}
		for value in (address, json.dumps(address)):
			with self.subTest(address=value):
				self.get_doc.reset_mock()
				self.create_customer(address=value)
				payload = self.get_doc.call_args_list[1].args[0]
				self.assertEqual(payload["doctype"], "Address")
				self.assertEqual(payload["address_line1"], "Street 1")
				self.assertEqual(payload["city"], "Cairo")
				self.assertEqual(payload["country"], "Egypt")
				self.assertEqual(payload["links"], [{"link_doctype": "Customer", "link_name": "CUSTOMER-1"}])

	def test_invalid_optional_values_are_rejected_before_creating_customer(self):
		for kwargs in (
			{"address": "invalid JSON"}, {"address": "[]"}, {"address": "false"},
			{"address": {"address_line1": "Street 1"}},
			{"additional_phones": "invalid JSON"}, {"additional_phones": "{}"},
		):
			with self.subTest(kwargs=kwargs):
				self.get_doc.reset_mock()
				with self.assertRaises(frappe.ValidationError):
					self.create_customer(**kwargs)
				self.get_doc.assert_not_called()

	def test_multiple_addresses_are_created_with_only_first_as_primary(self):
		created = []
		def get_doc(payload):
			if payload["doctype"] == "Customer":
				return self.customer
			address = MagicMock()
			address.name = f"ADDRESS-{len(created) + 1}"
			created.append(payload)
			return address
		self.get_doc.side_effect = get_doc
		self.create_customer(addresses=json.dumps([
			{"address_line1": "Home", "city": "Cairo"},
			{"address_line1": "Office", "city": "Giza"},
		]))
		self.assertEqual([row["address_line1"] for row in created], ["Home", "Office"])
		self.assertEqual([row["is_primary_address"] for row in created], [1, 0])
		self.assertEqual([row["is_shipping_address"] for row in created], [1, 0])
		self.customer.db_set.assert_called_once_with("customer_primary_address", "ADDRESS-1")

	def configure_update(self, shared=False):
		contact = MagicMock()
		contact.name = "CONTACT-1"
		contact.links = [SimpleNamespace(link_doctype="Customer", link_name=self.customer.name)]
		if shared:
			contact.links.append(SimpleNamespace(link_doctype="Customer", link_name="OTHER-CUSTOMER"))
		contact.phone_nos = [SimpleNamespace(name="PHONE-1", phone="02344324", is_primary_mobile_no=1)]
		contact.append.side_effect = lambda field, row: contact.phone_nos.append(SimpleNamespace(**row))
		def save(**kwargs):
			contact.mobile_no = next(row.phone for row in contact.phone_nos if row.is_primary_mobile_no)
		contact.save.side_effect = save
		self.get_doc.side_effect = lambda doctype, *args: self.customer if doctype == "Customer" else contact
		return contact

	def test_update_preserves_existing_phone_and_primary_address_and_adds_new_details(self):
		contact = self.configure_update()
		self.customer.customer_primary_address = "OLD-ADDRESS"
		address_doc = MagicMock()
		address_doc.name = "NEW-ADDRESS"
		self.get_doc.side_effect = lambda doctype, *args: (
			address_doc if isinstance(doctype, dict) else self.customer if doctype == "Customer" else contact)
		result = update_customer("CUSTOMER-1", "Ahmed Ali", "01012345678", "STORE-1",
			additional_phones='["01011111111", "010 1111 1111"]',
			addresses='[{"address_line1": "Office", "city": "Cairo"}]')
		self.assertEqual(result["customer_name"], "Ahmed Ali")
		self.assertEqual(result["mobile_no"], "01012345678")
		self.assertEqual([row.phone for row in contact.phone_nos], ["02344324", "01012345678", "01011111111"])
		self.assertEqual([row.is_primary_mobile_no for row in contact.phone_nos], [0, 1, 0])
		contact.save.assert_called_once_with(ignore_permissions=True)
		self.customer.save.assert_called_once_with(ignore_permissions=True)
		self.customer.db_set.assert_not_called()
		payload = self.get_doc.call_args.args[0]
		self.assertEqual(payload["links"], [{"link_doctype": "Customer", "link_name": "CUSTOMER-1"}])
		self.assertEqual(payload["is_primary_address"], 0)

	def test_shared_contact_is_not_modified(self):
		shared_contact = self.configure_update(shared=True)
		new_contact = MagicMock()
		new_contact.name = "DEDICATED-CONTACT"
		new_contact.mobile_no = "01012345678"
		new_contact.phone_nos = []
		new_contact.append.side_effect = lambda field, row: new_contact.phone_nos.append(SimpleNamespace(**row))
		self.get_doc.side_effect = lambda doctype, *args: (
			new_contact if isinstance(doctype, dict) else self.customer if doctype == "Customer" else shared_contact)
		update_customer("CUSTOMER-1", "Ahmed", "01012345678", "STORE-1")
		shared_contact.save.assert_not_called()
		shared_contact.append.assert_not_called()
		new_contact.insert.assert_called_once_with(ignore_permissions=True)
		self.assertEqual(self.customer.customer_primary_contact, "DEDICATED-CONTACT")

	def test_customer_details_include_all_linked_phones_and_addresses(self):
		with patch("rms.api.pos.frappe.get_all", side_effect=[
			["CONTACT-1", "CONTACT-2"], [frappe._dict(name="PHONE-1", contact="CONTACT-1", phone="02344324"),
				frappe._dict(name="PHONE-2", contact="CONTACT-2", phone="01012345678")],
			["ADDRESS-1", "ADDRESS-2"], [frappe._dict(name="ADDRESS-1"), frappe._dict(name="ADDRESS-2")],
		]) as get_all:
			details = get_customer_details("CUSTOMER-1", "STORE-1")
		self.assertEqual(details["phones"], ["02344324", "01012345678"])
		self.assertEqual(len(details["addresses"]), 2)
		self.assertEqual([row["is_default"] for row in details["phone_rows"]], [True, False])
		self.assertEqual([row["is_default"] for row in details["addresses"]], [True, False])
		self.assertEqual(get_all.call_args_list[0].kwargs["filters"], {
			"parenttype": "Contact", "link_doctype": "Customer", "link_name": "CUSTOMER-1"})
		self.assertEqual(get_all.call_args_list[2].kwargs["filters"]["parenttype"], "Address")

	def test_invalid_update_is_rejected_before_saving(self):
		for kwargs in ({"addresses": '[{"city": "Cairo"}]'}, {"addresses": "{}"},
			{"additional_phones": "oops"}, {"additional_phones": '[42]'}):
			with self.subTest(kwargs=kwargs):
				contact = self.configure_update()
				with self.assertRaises(frappe.ValidationError):
					update_customer("CUSTOMER-1", "Ahmed", "01012345678", "STORE-1", **kwargs)
				contact.save.assert_not_called()
				self.customer.save.assert_not_called()

	def test_store_permissions_are_required_for_read_and_update(self):
		with patch("rms.api.pos.assert_store_access", side_effect=frappe.PermissionError):
			with self.assertRaises(frappe.PermissionError):
				get_customer_details("CUSTOMER-1", "DENIED")
			with self.assertRaises(frappe.PermissionError):
				update_customer("CUSTOMER-1", "Ahmed", "01012345678", "DENIED")
		self.get_doc.assert_not_called()

	def test_disabled_customers_cannot_be_read_or_updated(self):
		self.customer.disabled = 1
		with self.assertRaises(frappe.ValidationError):
			get_customer_details("CUSTOMER-1", "STORE-1")
		with self.assertRaises(frappe.ValidationError):
			update_customer("CUSTOMER-1", "Ahmed", "01012345678", "STORE-1")
		self.customer.save.assert_not_called()

	def test_editor_requires_one_default_phone_and_one_default_address(self):
		for phones, addresses in (
			([], []),
			([{"phone": "01012345678"}], []),
			([{"phone": "01012345678", "is_default": True}, {"phone": "01011111111", "is_default": True}], []),
			([{"phone": "01012345678", "is_default": 2}], []),
			([{"phone": "01012345678", "is_default": True}], [{"address_line1": "Street", "city": "Cairo"}]),
		):
			with self.subTest(phones=phones, addresses=addresses):
				with self.assertRaises(frappe.ValidationError):
					save_customer_details("Ahmed", "STORE-1", phones, addresses, customer="CUSTOMER-1")
		self.get_doc.assert_not_called()

	def test_editor_does_not_accept_another_customers_phone_or_address_id(self):
		for phones, addresses in (
			([{"name": "OTHER-PHONE", "contact": "OTHER-CONTACT", "phone": "01012345678", "is_default": True}], []),
			([{"phone": "01012345678", "is_default": True}],
				[{"name": "OTHER-ADDRESS", "address_line1": "Street", "city": "Cairo", "is_default": True}]),
		):
			with self.subTest(phones=phones, addresses=addresses), \
					patch("rms.api.pos._customer_linked_names", return_value=[]):
				with self.assertRaises(frappe.PermissionError):
					save_customer_details("Ahmed", "STORE-1", phones, addresses, customer="CUSTOMER-1")
		self.customer.save.assert_not_called()

	def test_editor_creates_customer_using_selected_defaults(self):
		with patch("rms.api.pos.create_customer", return_value={"name": "NEW"}) as create:
			result = save_customer_details("Ahmed", "STORE-1", [
				{"phone": "01011111111", "is_default": False}, {"phone": "01022222222", "is_default": True},
			], [
				{"address_line1": "Home", "city": "Cairo", "is_default": False},
				{"address_line1": "Office", "city": "Giza", "is_default": True},
			])
		self.assertEqual(result["name"], "NEW")
		self.assertEqual(create.call_args.args[1], "01022222222")
		self.assertEqual(create.call_args.kwargs["additional_phones"], ["01011111111"])
		self.assertEqual([row["address_line1"] for row in create.call_args.kwargs["addresses"]], ["Office", "Home"])

	def test_editor_updates_saved_rows_and_switches_defaults_without_duplicates(self):
		contact = self.configure_update()
		contact.phone_nos.append(SimpleNamespace(name="PHONE-2", phone="01011111111", is_primary_mobile_no=0))
		addresses = {}
		for name in ("ADDRESS-1", "ADDRESS-2"):
			address = MagicMock()
			address.name = name
			address.disabled = 0
			address.links = [SimpleNamespace(link_doctype="Customer", link_name="CUSTOMER-1")]
			addresses[name] = address
		self.get_doc.side_effect = lambda doctype, name: (
			self.customer if doctype == "Customer" else contact if doctype == "Contact" else addresses[name])
		with patch("rms.api.pos._customer_linked_names", side_effect=lambda customer, parenttype:
			["CONTACT-1"] if parenttype == "Contact" else list(addresses)):
			save_customer_details("Ahmed Ali", "STORE-1", [
				{"name": "PHONE-1", "contact": "CONTACT-1", "phone": "02344324", "is_default": False},
				{"name": "PHONE-2", "contact": "CONTACT-1", "phone": "01022222222", "is_default": True},
			], [
				{"name": "ADDRESS-1", "address_line1": "Home", "city": "Cairo", "is_default": False},
				{"name": "ADDRESS-2", "address_line1": "Edited Office", "city": "Giza", "is_default": True},
			], customer="CUSTOMER-1")
		self.assertEqual([row.phone for row in contact.phone_nos], ["02344324", "01022222222"])
		self.assertEqual([row.is_primary_mobile_no for row in contact.phone_nos], [0, 1])
		contact.append.assert_not_called()
		self.assertEqual(self.customer.mobile_no, "01022222222")
		addresses["ADDRESS-2"].update.assert_called_once_with({
			"address_line1": "Edited Office", "address_line2": "", "city": "Giza", "state": ""})
		self.assertEqual(addresses["ADDRESS-1"].is_primary_address, 0)
		self.assertEqual(addresses["ADDRESS-2"].is_primary_address, 1)
		for address in addresses.values():
			address.insert.assert_not_called()
			address.save.assert_called_once_with(ignore_permissions=True)
		self.customer.db_set.assert_called_once_with("customer_primary_address", "ADDRESS-2")
