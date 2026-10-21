import unittest

import frappe

from rms.api.pos import _normalize_actual_amounts


class TestPOSSessionCloseCounts(unittest.TestCase):
	def test_explicit_zero_is_a_valid_actual_count(self):
		self.assertEqual(_normalize_actual_amounts({"Cash": 0, "Card": "0"}, ["Cash", "Card"]), {
			"Cash": 0, "Card": 0,
		})

	def test_blank_actual_count_is_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Enter an actual amount"):
			_normalize_actual_amounts({"Cash": "   "}, ["Cash"])

	def test_missing_actual_count_is_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Enter an actual amount"):
			_normalize_actual_amounts({}, ["Cash"])

	def test_non_numeric_actual_count_is_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "valid non-negative amount"):
			_normalize_actual_amounts({"Cash": "cash"}, ["Cash"])

	def test_negative_actual_count_is_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "valid non-negative amount"):
			_normalize_actual_amounts({"Cash": -1}, ["Cash"])

	def test_unconfigured_payment_method_is_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "payment methods configured"):
			_normalize_actual_amounts({"Cash": 10, "Bitcoin": 5}, ["Cash"])
