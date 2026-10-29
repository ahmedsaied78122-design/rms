import unittest
from decimal import Decimal
from types import SimpleNamespace

from rms.pos_rounding import apply_pos_brand_rounding, round_pos_payable, POSInvoiceRoundingMixin


class TestPOSRounding(unittest.TestCase):
	def test_migrated_brand_setting_and_invoice_extension_are_available(self):
		import frappe
		from frappe.model.base_document import get_controller

		field = frappe.get_meta("Restaurant Brand").get_field("pos_rounding_method")
		self.assertIsNotNone(field)
		self.assertIn("No Rounding", field.options)
		controller = get_controller("POS Invoice")
		self.assertIn(POSInvoiceRoundingMixin, controller.__mro__)

	def test_8049_rounds_up_to_81_and_nearest_or_down_to_80(self):
		amount = Decimal("80.49")
		self.assertEqual(round_pos_payable(amount, "Round Up"), Decimal("81"))
		self.assertEqual(round_pos_payable(amount, "Nearest"), Decimal("80"))
		self.assertEqual(round_pos_payable(amount, "Round Down"), Decimal("80"))

	def test_nearest_half_pound_rounds_up(self):
		self.assertEqual(round_pos_payable(Decimal("77.50"), "Nearest"), Decimal("78"))

	def test_blank_method_defaults_to_nearest(self):
		self.assertEqual(round_pos_payable(Decimal("77.50"), ""), Decimal("78"))

	def test_exact_integer_and_zero_are_unchanged(self):
		for method in ("Round Up", "Nearest", "Round Down", "No Rounding"):
			self.assertEqual(round_pos_payable(Decimal("80.00"), method), Decimal("80"))
			self.assertEqual(round_pos_payable(Decimal("0"), method), Decimal("0"))

	def test_no_rounding_preserves_fractional_payable(self):
		self.assertEqual(round_pos_payable(Decimal("80.49"), "No Rounding"), Decimal("80.49"))

	def test_invoice_rounding_fields_include_the_brand_adjustment(self):
		invoice = SimpleNamespace(
			flags=SimpleNamespace(rms_pos_rounding_method="Round Up"), grand_total=80.49,
			base_grand_total=80.49, conversion_rate=1, disable_rounded_total=1,
			precision=lambda fieldname: 2,
		)
		apply_pos_brand_rounding(invoice)
		self.assertEqual(invoice.rounded_total, 81)
		self.assertEqual(invoice.rounding_adjustment, 0.51)
		self.assertEqual(invoice.base_rounded_total, 81)
		self.assertEqual(invoice.base_rounding_adjustment, 0.51)
		self.assertEqual(invoice.disable_rounded_total, 0)

	def test_round_down_preserves_negative_round_off_adjustment(self):
		invoice = SimpleNamespace(
			flags=SimpleNamespace(rms_pos_rounding_method="Round Down"), grand_total=80.49,
			base_grand_total=80.49, conversion_rate=1, disable_rounded_total=1,
			precision=lambda fieldname: 2,
		)
		apply_pos_brand_rounding(invoice)
		self.assertEqual(invoice.rounded_total, 80)
		self.assertEqual(invoice.rounding_adjustment, -0.49)
		self.assertEqual(invoice.base_rounding_adjustment, -0.49)

	def test_no_rounding_invoice_preserves_cents_without_adjustment(self):
		invoice = SimpleNamespace(
			flags=SimpleNamespace(rms_pos_rounding_method="No Rounding"), grand_total=80.49,
			base_grand_total=80.49, conversion_rate=1, disable_rounded_total=0,
			precision=lambda fieldname: 2,
		)
		apply_pos_brand_rounding(invoice)
		self.assertEqual(invoice.rounded_total, 80.49)
		self.assertEqual(invoice.rounding_adjustment, 0)
		self.assertEqual(invoice.base_rounded_total, 80.49)
		self.assertEqual(invoice.base_rounding_adjustment, 0)
		self.assertEqual(invoice.disable_rounded_total, 1)

	def test_pos_invoice_extension_reapplies_brand_rounding_after_erpnext_calculation(self):
		class ERPNextInvoice:
			def calculate_taxes_and_totals(self):
				self.rounded_total = 80

		class POSInvoice(POSInvoiceRoundingMixin, ERPNextInvoice):
			pass

		invoice = POSInvoice()
		invoice.flags = SimpleNamespace(rms_pos_rounding_method="Round Up")
		invoice.grand_total = 80.49
		invoice.base_grand_total = 80.49
		invoice.conversion_rate = 1
		invoice.disable_rounded_total = 1
		invoice.precision = lambda fieldname: 2
		invoice.calculate_taxes_and_totals()
		self.assertEqual(invoice.rounded_total, 81)
		self.assertEqual(invoice.rounding_adjustment, 0.51)

	def test_invoice_without_brand_rounding_flag_keeps_erpnext_totals(self):
		class ERPNextInvoice:
			def calculate_taxes_and_totals(self):
				self.rounded_total = 80

		class POSInvoice(POSInvoiceRoundingMixin, ERPNextInvoice):
			pass

		invoice = POSInvoice()
		invoice.flags = SimpleNamespace()
		invoice.grand_total = 80.49
		invoice.calculate_taxes_and_totals()
		self.assertEqual(invoice.rounded_total, 80)

	def test_pos_invoice_extension_respects_no_rounding(self):
		class ERPNextInvoice:
			def calculate_taxes_and_totals(self):
				self.rounded_total = 80.49 if self.disable_rounded_total else 80

		class POSInvoice(POSInvoiceRoundingMixin, ERPNextInvoice):
			pass

		invoice = POSInvoice()
		invoice.flags = SimpleNamespace(rms_pos_rounding_method="No Rounding")
		invoice.grand_total = 80.49
		invoice.base_grand_total = 80.49
		invoice.conversion_rate = 1
		invoice.disable_rounded_total = 0
		invoice.precision = lambda fieldname: 2
		invoice.calculate_taxes_and_totals()
		self.assertEqual(invoice.rounded_total, 80.49)
		self.assertEqual(invoice.rounding_adjustment, 0)
		self.assertEqual(invoice.disable_rounded_total, 1)


if __name__ == "__main__":
	unittest.main()
