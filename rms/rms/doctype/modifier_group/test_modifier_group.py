import unittest

import frappe

from rms.rms.doctype.modifier_group.modifier_group import ModifierGroup


class TestModifierGroupMinimum(unittest.TestCase):
	def validate_group(self, minimum, multiple=False):
		ModifierGroup.validate(frappe._dict(min_selections=minimum,
			allow_multiple_selections=multiple, collapsed_by_default=0))

	def test_optional_and_required_single_choice(self):
		self.validate_group(0)
		self.validate_group(1)

	def test_multiple_choice_can_require_more_than_one(self):
		self.validate_group(2, multiple=True)

	def test_negative_minimum_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.validate_group(-1)

	def test_single_choice_cannot_require_two(self):
		with self.assertRaises(frappe.ValidationError):
			self.validate_group(2)

class TestModifierGroupMaximum(unittest.TestCase):
	def validate(self, minimum=0, maximum=0, multiple=True):
		ModifierGroup.validate(frappe._dict(min_selections=minimum,max_selections=maximum,
			allow_multiple_selections=multiple,collapsed_by_default=0))

	def test_unlimited_multiple_choice_preserves_existing_configuration(self):
		self.validate(2,0)

	def test_minimum_and_maximum_can_be_equal(self):
		self.validate(2,2)

	def test_maximum_below_minimum_is_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError,"lower than"):
			self.validate(3,2)

	def test_negative_maximum_is_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError,"negative"):
			self.validate(0,-1)

	def test_single_choice_cannot_allow_two(self):
		with self.assertRaisesRegex(frappe.ValidationError,"single-choice"):
			self.validate(0,2,False)
