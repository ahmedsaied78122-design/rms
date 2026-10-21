import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

import frappe
from rms.api.pos import _apply_order_discount, _apply_order_tax_template
import rms.taxes as rms_taxes
from rms.taxes import prevent_pos_item_price_autoinsert


class TestPOSOrderTaxTemplate(unittest.TestCase):
	def _allow_rms_cashier_session_pos_invoice(self, invoice, session):
		helper = getattr(rms_taxes, "allow_rms_cashier_session_pos_invoice", None)
		self.assertTrue(callable(helper), "RMS needs a scoped POS Opening Entry validator for its active cashier session")
		return helper(invoice, session, "cashier@example.com")

	def test_invoice_accepts_an_older_opening_entry_for_its_active_cashier_session(self):
		invoice = Mock(pos_profile="PROFILE-1", company="COMPANY-1")
		session = SimpleNamespace(name="SESSION-1", user="cashier@example.com", status="Open",
			pos_profile="PROFILE-1", pos_opening_entry="OPENING-1")
		original_validator = invoice.validate_pos_opening_entry
		opening = frappe._dict(name="OPENING-1", pos_profile="PROFILE-1", user="cashier@example.com",
			company="COMPANY-1", status="Open", docstatus=1, period_start_date="2026-10-19 14:39:00")
		with patch("frappe.get_all", return_value=[opening]):
			with self._allow_rms_cashier_session_pos_invoice(invoice, session):
				self.assertIsNone(invoice.validate_pos_opening_entry())
		self.assertIs(invoice.validate_pos_opening_entry, original_validator)

	def test_rms_cashier_session_override_rejects_an_unrelated_opening_entry(self):
		invoice = Mock(pos_profile="PROFILE-1", company="COMPANY-1")
		session = SimpleNamespace(name="SESSION-1", user="cashier@example.com", status="Open",
			pos_profile="PROFILE-1", pos_opening_entry="OPENING-1")
		opening = frappe._dict(name="OPENING-OTHER", pos_profile="PROFILE-1", user="other@example.com",
			company="COMPANY-1", status="Open", docstatus=1, period_start_date="2026-10-19 14:39:00")
		with patch("frappe.get_all", return_value=[opening]):
			with self._allow_rms_cashier_session_pos_invoice(invoice, session):
				with self.assertRaisesRegex(frappe.ValidationError, "must match the active Cashier Session"):
					invoice.validate_pos_opening_entry()

	def test_rms_cashier_session_override_rejects_multiple_opening_entries(self):
		invoice = Mock(pos_profile="PROFILE-1", company="COMPANY-1")
		session = SimpleNamespace(name="SESSION-1", user="cashier@example.com", status="Open",
			pos_profile="PROFILE-1", pos_opening_entry="OPENING-1")
		entries = [frappe._dict(name=name, pos_profile="PROFILE-1", user="cashier@example.com",
			company="COMPANY-1", status="Open", docstatus=1, period_start_date="2026-10-19 14:39:00")
			for name in ("OPENING-1", "OPENING-2")]
		with patch("frappe.get_all", return_value=entries):
			with self._allow_rms_cashier_session_pos_invoice(invoice, session):
				with self.assertRaisesRegex(frappe.ValidationError, "multiple open POS Opening Entries"):
					invoice.validate_pos_opening_entry()

	def test_rms_cashier_session_override_rejects_a_closed_session(self):
		invoice = Mock(pos_profile="PROFILE-1", company="COMPANY-1")
		session = SimpleNamespace(name="SESSION-1", user="cashier@example.com", status="Closed",
			pos_profile="PROFILE-1", pos_opening_entry="OPENING-1")
		with self._allow_rms_cashier_session_pos_invoice(invoice, session):
			with self.assertRaisesRegex(frappe.ValidationError, "must match the active Cashier Session"):
				invoice.validate_pos_opening_entry()

	def test_rms_cashier_session_override_rejects_a_future_opening_period(self):
		invoice = Mock(pos_profile="PROFILE-1", company="COMPANY-1")
		session = SimpleNamespace(name="SESSION-1", user="cashier@example.com", status="Open",
			pos_profile="PROFILE-1", pos_opening_entry="OPENING-1")
		opening = frappe._dict(name="OPENING-1", pos_profile="PROFILE-1", user="cashier@example.com",
			company="COMPANY-1", status="Open", docstatus=1, period_start_date="2099-10-19 14:39:00")
		with patch("frappe.get_all", return_value=[opening]):
			with self._allow_rms_cashier_session_pos_invoice(invoice, session):
				with self.assertRaisesRegex(frappe.ValidationError, "cannot start in the future"):
					invoice.validate_pos_opening_entry()

	def test_pos_invoice_defaults_skip_generic_item_price_lookup_and_restore_it(self):
		invoice = Mock()
		item_detail_lookup = invoice.set_missing_item_details
		invoice.set_missing_values.side_effect = lambda: invoice.set_missing_item_details(for_validate=True)

		with prevent_pos_item_price_autoinsert(invoice):
			invoice.set_missing_values()
			item_detail_lookup.assert_not_called()

		invoice.set_missing_item_details()
		item_detail_lookup.assert_called_once_with()

	def test_pos_invoice_default_context_restores_item_lookup_after_failure(self):
		invoice = Mock()
		original_lookup = invoice.set_missing_item_details

		with self.assertRaisesRegex(RuntimeError, "invoice setup failed"):
			with prevent_pos_item_price_autoinsert(invoice):
				raise RuntimeError("invoice setup failed")

		self.assertIs(invoice.set_missing_item_details, original_lookup)

	def test_order_type_tax_template_replaces_rows_loaded_from_pos_profile(self):
		invoice = Mock()
		invoice.taxes_and_charges = "POS Profile - 20%"
		invoice.taxes = [{"account_head": "Profile Tax Payable - RMS", "rate": 20}]
		invoice.set.side_effect = lambda fieldname, value: setattr(invoice, fieldname, value)

		_apply_order_tax_template(invoice, "Dine In - 12%")

		self.assertEqual(invoice.taxes_and_charges, "Dine In - 12%")
		self.assertEqual(invoice.taxes, [])
		invoice.set.assert_called_once_with("taxes", [])
		invoice.set_taxes.assert_called_once_with()

	def test_missing_template_clears_profile_tax_rows_without_loading_new_taxes(self):
		invoice = Mock()
		invoice.taxes_and_charges = "POS Profile - 20%"
		invoice.taxes = [{"account_head": "Profile Tax Payable - RMS", "rate": 20}]
		invoice.set.side_effect = lambda fieldname, value: setattr(invoice, fieldname, value)

		_apply_order_tax_template(invoice, None)

		self.assertIsNone(invoice.taxes_and_charges)
		self.assertEqual(invoice.taxes, [])
		invoice.set_taxes.assert_not_called()

	def test_percentage_discount_replaces_profile_discount_settings(self):
		invoice = Mock(apply_discount_on="Net Total", discount_amount=5, additional_discount_percentage=7)
		order = Mock(discount_scope="Grand Total", discount_type="Percentage", discount_value=10, discount_amount=12.77)

		_apply_order_discount(invoice, order)

		self.assertEqual(invoice.apply_discount_on, "Grand Total")
		self.assertEqual(invoice.discount_amount, 0)
		self.assertEqual(invoice.additional_discount_percentage, 10)

	def test_fixed_discount_clears_percentage_from_profile(self):
		invoice = Mock(apply_discount_on="Grand Total", discount_amount=5, additional_discount_percentage=7)
		order = Mock(discount_scope="Net Total", discount_type="Amount", discount_amount=15.5)

		_apply_order_discount(invoice, order)

		self.assertEqual(invoice.apply_discount_on, "Net Total")
		self.assertEqual(invoice.discount_amount, 15.5)
		self.assertEqual(invoice.additional_discount_percentage, 0)
