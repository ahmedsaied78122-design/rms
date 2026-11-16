import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from rms.rms.doctype.order_type.order_type import OrderType


class TestOrderTypeRename(unittest.TestCase):
	def setUp(self):
		stack = ExitStack()
		self.addCleanup(stack.close)
		self.rules = stack.enter_context(patch('rms.rms.doctype.order_type.order_type.frappe.get_all'))
		self.rules.return_value = [frappe._dict(parent='P1', store='Maadi', restaurant_brand='East'),
			frappe._dict(parent='P2', store='Maadi', restaurant_brand='East')]
		product = SimpleNamespace(get_price_currencies=lambda store: ['EGP'],
			get_price_list_name=lambda conditions, currency: f"Generated-{conditions['order_type']}-{currency}")
		stack.enter_context(patch('rms.rms.doctype.order_type.order_type.frappe.get_doc', return_value=product))
		self.db = stack.enter_context(patch('rms.rms.doctype.order_type.order_type.frappe.db', new=MagicMock(), create=True))
		self.db.exists.side_effect = lambda dt, name: name == 'Generated-توصيل-EGP'
		self.rename = stack.enter_context(patch('rms.rms.doctype.order_type.order_type.frappe.rename_doc'))
		self.enqueue = stack.enter_context(patch('rms.rms.doctype.order_type.order_type.frappe.enqueue'))
		stack.enter_context(patch('rms.rms.doctype.order_type.order_type._', side_effect=lambda message: message))
		stack.enter_context(patch('rms.rms.doctype.order_type.order_type.frappe.throw', side_effect=frappe.ValidationError))

	def test_shared_generated_list_is_renamed_once_and_keeps_native_link_updates(self):
		OrderType.after_rename(None, 'توصيل', 'Delivery')
		self.rules.assert_called_once_with('Selling Product Price Rule', filters={'order_type': 'Delivery'},
			fields=['parent', 'store', 'restaurant_brand'])
		self.rename.assert_called_once_with('Price List', 'Generated-توصيل-EGP', 'Generated-Delivery-EGP',
			show_alert=False, rebuild_search=False)
		self.enqueue.assert_called_once_with('frappe.utils.global_search.rebuild_for_doctype',
			doctype='Price List', enqueue_after_commit=True)

	def test_existing_target_is_not_merged_or_overwritten(self):
		self.db.exists.return_value = True
		self.db.exists.side_effect = None
		with self.assertRaises(frappe.ValidationError):
			OrderType.after_rename(None, 'توصيل', 'Delivery')
		self.rename.assert_not_called()
		self.enqueue.assert_not_called()

	def test_uncompiled_or_absent_prices_do_not_create_new_price_records(self):
		self.db.exists.side_effect = None
		self.db.exists.return_value = False
		OrderType.after_rename(None, 'توصيل', 'Delivery')
		self.rename.assert_not_called()
		self.enqueue.assert_not_called()


if __name__ == '__main__':
	unittest.main()
