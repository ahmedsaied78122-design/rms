import unittest
from unittest.mock import patch

import frappe

from rms.rms.doctype.selling_product.selling_product import SellingProduct


class TestOptionAttributes(unittest.TestCase):
	def product(self, values):
		return frappe._dict(name='Tea', has_options=1, option_attribute='Size', option_products=[
			frappe._dict(option_product=f'OPTION-{n}', attribute_value=value) for n, value in enumerate(values)
		])

	def attribute(self, **values):
		return frappe._dict(name='Size', disabled=0, numeric_values=0,
			item_attribute_values=[frappe._dict(attribute_value=v) for v in ['Small', 'Large']], **values)

	def test_attribute_values_are_validated_and_trimmed(self):
		product = self.product([' Small ', 'Large'])
		with patch('frappe.get_doc', return_value=self.attribute()):
			SellingProduct.validate_option_attribute(product)
		self.assertEqual(product.option_products[0].attribute_value, 'Small')

	def test_missing_value_is_rejected(self):
		with patch('frappe.get_doc', return_value=self.attribute()):
			with self.assertRaisesRegex(frappe.ValidationError, 'Attribute Value'):
				SellingProduct.validate_option_attribute(self.product(['']))

	def test_value_outside_the_attribute_is_rejected(self):
		with patch('frappe.get_doc', return_value=self.attribute()):
			with self.assertRaises(frappe.ValidationError):
				SellingProduct.validate_option_attribute(self.product(['Unknown']))

	def test_duplicate_values_are_rejected(self):
		with patch('frappe.get_doc', return_value=self.attribute()):
			with self.assertRaisesRegex(frappe.ValidationError, 'different Attribute Value'):
				SellingProduct.validate_option_attribute(self.product(['Small', 'Small']))

	def test_disabled_attribute_is_rejected(self):
		attribute = self.attribute(); attribute.disabled = 1
		with patch('frappe.get_doc', return_value=attribute):
			with self.assertRaisesRegex(frappe.ValidationError, 'enabled Option Attribute'):
				SellingProduct.validate_option_attribute(self.product(['Small']))

	def test_legacy_products_do_not_need_an_attribute(self):
		product = self.product(['']); product.option_attribute = None
		with patch('frappe.get_doc') as get_doc:
			SellingProduct.validate_option_attribute(product)
			get_doc.assert_not_called()

	def test_numeric_attribute_accepts_zero(self):
		attribute = self.attribute(); attribute.numeric_values = 1
		attribute.from_range = 0; attribute.to_range = 10; attribute.increment = 1
		with patch('frappe.get_doc', return_value=attribute):
			SellingProduct.validate_option_attribute(self.product([0]))

	def test_numeric_attribute_rejects_values_between_increments(self):
		attribute = self.attribute(); attribute.numeric_values = 1
		attribute.from_range = 0; attribute.to_range = 10; attribute.increment = 1
		with patch('frappe.get_doc', return_value=attribute):
			with self.assertRaises(frappe.ValidationError):
				SellingProduct.validate_option_attribute(self.product(['1.5']))

	def test_numeric_attribute_rejects_text(self):
		attribute = self.attribute(); attribute.numeric_values = 1
		attribute.from_range = 0; attribute.to_range = 10; attribute.increment = 1
		with patch('frappe.get_doc', return_value=attribute):
			with self.assertRaisesRegex(frappe.ValidationError, 'must be a number'):
				SellingProduct.validate_option_attribute(self.product(['abc']))

	def test_numeric_attribute_rejects_equivalent_duplicate_values(self):
		attribute = self.attribute(); attribute.numeric_values = 1
		attribute.from_range = 0; attribute.to_range = 10; attribute.increment = 1
		with patch('frappe.get_doc', return_value=attribute):
			with self.assertRaisesRegex(frappe.ValidationError, 'different Attribute Value'):
				SellingProduct.validate_option_attribute(self.product(['1', '1.0']))
