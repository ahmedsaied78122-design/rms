import unittest
from types import SimpleNamespace
from unittest.mock import patch
import frappe
from rms.stock import ensure_void_stock_entry_type, prevent_duplicate_return_stock


class TestStockEffects(unittest.TestCase):
	def invoice(self, returns=True, consolidated=True, sources=('RMS-CREDIT',)):
		return SimpleNamespace(is_return=returns, is_consolidated=consolidated, update_stock=1,
			items=[frappe._dict(pos_invoice=name) for name in sources])

	def test_consolidated_rms_credit_does_not_receive_stock_twice(self):
		doc=self.invoice()
		with patch('rms.stock.frappe.get_all',return_value=['RMS-CREDIT']):
			prevent_duplicate_return_stock(doc)
		self.assertEqual(doc.update_stock,0)

	def test_standard_sales_and_external_returns_keep_standard_stock_effects(self):
		for doc in (self.invoice(returns=False),self.invoice(consolidated=False),self.invoice(sources=('EXTERNAL',))):
			with patch('rms.stock.frappe.get_all',return_value=[]):
				prevent_duplicate_return_stock(doc)
			self.assertEqual(doc.update_stock,1)

	def test_mixing_manually_received_and_standard_returns_is_rejected(self):
		with patch('rms.stock.frappe.get_all',return_value=['RMS-CREDIT']),self.assertRaises(frappe.ValidationError):
			prevent_duplicate_return_stock(self.invoice(sources=('RMS-CREDIT','EXTERNAL')))

	def test_void_is_a_material_issue_type(self):
		with patch('rms.stock.frappe.db.exists',return_value=True),patch('rms.stock.frappe.db.get_value',return_value='Material Issue'):
			self.assertEqual(ensure_void_stock_entry_type(),'Void')
		with patch('rms.stock.frappe.db.exists',return_value=True),patch('rms.stock.frappe.db.get_value',return_value='Material Receipt'),self.assertRaises(frappe.ValidationError):
			ensure_void_stock_entry_type()
