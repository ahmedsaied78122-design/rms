import unittest
from unittest.mock import patch

import frappe

from rms.rms.doctype.product_category.product_category import ProductCategory


class TestProductCategoryParentValidation(unittest.TestCase):
	def category(self):
		return frappe._dict(name='Pasta', parent_product_category='Italian', item_group='Products', is_group=0)

	def test_existing_parent_can_be_saved(self):
		with patch('frappe.db.get_value', side_effect=[
			frappe._dict(enabled=1, is_group=1, lft=1, rgt=10),
			frappe._dict(lft=2, rgt=3), 0,
		]):
			ProductCategory.validate(self.category())

	def test_category_can_move_to_an_unrelated_parent(self):
		with patch('frappe.db.get_value', side_effect=[
			frappe._dict(enabled=1, is_group=1, lft=12, rgt=20),
			frappe._dict(lft=2, rgt=3), 0,
		]):
			ProductCategory.validate(self.category())

	def test_parent_inside_current_subtree_is_rejected(self):
		with patch('frappe.db.get_value', side_effect=[
			frappe._dict(enabled=1, is_group=1, lft=3, rgt=4),
			frappe._dict(lft=2, rgt=9),
		]):
			with self.assertRaisesRegex(frappe.ValidationError, 'own descendants'):
				ProductCategory.validate(self.category())
