import frappe
from frappe.utils import add_days, get_datetime, get_time, getdate, now_datetime


def get_business_date(store, reference_datetime=None):
	"""Resolve a Store's operating date using its configured day-end cutoff."""
	cutoff = frappe.db.get_value("Store", store, "operating_day_end")
	current = get_datetime(reference_datetime or now_datetime())
	business_date = getdate(current)
	if cutoff and current.time() < get_time(cutoff):
		business_date = getdate(add_days(business_date, -1))
	return business_date


def get_business_date_sql(datetime_expression, cutoff_expression):
	"""Return the SQL equivalent of get_business_date for a trusted SQL expression pair."""
	return (
		f"CASE WHEN TIME({datetime_expression}) < COALESCE({cutoff_expression}, '00:00:00') "
		f"THEN DATE_SUB(DATE({datetime_expression}), INTERVAL 1 DAY) "
		f"ELSE DATE({datetime_expression}) END"
	)
