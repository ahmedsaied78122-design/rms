import unittest
from unittest.mock import patch

from frappe.utils import getdate

from rms.utils import get_business_date, get_business_date_sql


class TestBusinessDate(unittest.TestCase):
	@patch("frappe.db.get_value", return_value="04:00:00")
	def test_time_before_store_day_end_belongs_to_previous_business_day(self, get_value):
		self.assertEqual(get_business_date("STORE-1", "2026-10-19 03:59:59"), getdate("2026-10-18"))
		get_value.assert_called_once_with("Store", "STORE-1", "operating_day_end")

	@patch("frappe.db.get_value", return_value="04:00:00")
	def test_exactly_at_store_day_end_belongs_to_current_business_day(self, _get_value):
		self.assertEqual(get_business_date("STORE-1", "2026-10-19 04:00:00"), getdate("2026-10-19"))

	@patch("frappe.db.get_value", return_value=None)
	def test_missing_cutoff_uses_calendar_date(self, _get_value):
		self.assertEqual(get_business_date("STORE-1", "2026-10-19 00:01:00"), getdate("2026-10-19"))

	def test_sql_resolver_uses_same_strict_cutoff_rule(self):
		self.assertEqual(
			get_business_date_sql("ret.approved_at", "store.operating_day_end"),
			"CASE WHEN TIME(ret.approved_at) < COALESCE(store.operating_day_end, '00:00:00') "
			"THEN DATE_SUB(DATE(ret.approved_at), INTERVAL 1 DAY) "
			"ELSE DATE(ret.approved_at) END",
		)
