import unittest
from unittest.mock import patch

import frappe

from rms.order_naming import next_pos_order_name
from rms.rms.doctype.pos_order.pos_order import POSOrder


class TestOrderNaming(unittest.TestCase):
	def test_requested_format_uses_calendar_day_not_cashier_business_date(self):
		with patch("rms.order_naming.frappe.db.get_value", return_value="MAADI") as store_code, \
				patch("rms.order_naming.nowdate", return_value="2026-11-09"), \
				patch("rms.order_naming._next_order_sequence", return_value="0023") as series:
			self.assertEqual(next_pos_order_name("Store-1"), ("maadi-09112026-0023", "maadi-09112026-"))
		store_code.assert_called_once_with("Store", "Store-1", "store_code", for_update=True)
		series.assert_called_once_with("maadi-09112026-")

	def test_twenty_branches_and_days_have_independent_database_counters(self):
		marker = "naming-test-" + frappe.generate_hash(length=10)
		frappe.db.savepoint("order_naming_test")
		try:
			with patch("rms.order_naming.frappe.db.get_value", side_effect=lambda doctype, store, field, **kw: store), \
					patch("rms.order_naming.nowdate", return_value="2026-11-09"):
				names = []
				for branch in range(20):
					code = f"{marker}-{branch}"
					first, prefix = next_pos_order_name(code)
					second, _ = next_pos_order_name(code)
					self.assertEqual(first, prefix + "0001")
					self.assertEqual(second, prefix + "0002")
					names.extend([first, second])
				self.assertEqual(len(set(names)), 40)
				with patch("rms.order_naming.nowdate", return_value="2026-11-10"):
					next_day, prefix = next_pos_order_name(f"{marker}-0")
					self.assertEqual(next_day, prefix + "0001")
		finally:
			frappe.db.rollback(save_point="order_naming_test")

	def test_sequence_can_grow_beyond_four_digits(self):
		with patch("rms.order_naming.frappe.db.get_value", return_value="MAADI"), \
				patch("rms.order_naming.nowdate", return_value="2026-11-09"), \
				patch("rms.order_naming._next_order_sequence", return_value="10000"):
			self.assertEqual(next_pos_order_name("Store-1")[0], "maadi-09112026-10000")

	def test_controller_assigns_complete_name_and_its_series(self):
		doc = frappe.new_doc("POS Order")
		doc.store = "Store-1"
		with patch("rms.order_naming.next_pos_order_name", return_value=("maadi-09112026-0023", "maadi-09112026-")):
			POSOrder.autoname(doc)
		self.assertEqual(doc.name, "maadi-09112026-0023")
		self.assertEqual(doc.naming_series, "maadi-09112026-")

	def test_missing_store_code_cannot_fall_back_to_a_shared_counter(self):
		for code in (None, "", "  "):
			with self.subTest(code=code), patch("rms.order_naming.frappe.db.get_value", return_value=code), \
					patch("rms.order_naming._next_order_sequence") as series:
				with self.assertRaises(frappe.ValidationError):
					next_pos_order_name("Store-1")
			series.assert_not_called()
