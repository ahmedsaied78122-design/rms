frappe.query_reports["RMS Cashier Session Reconciliation"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.month_start() },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today() },
		{ fieldname: "store", label: __("Store"), fieldtype: "Link", options: "Store", get_query: () => ({ filters: { enabled: 1 } }) },
		{ fieldname: "cashier", label: __("Cashier"), fieldtype: "Link", options: "User", get_query: () => ({ filters: { enabled: 1 } }) },
		{ fieldname: "status", label: __("Session Status"), fieldtype: "Select", options: "\nOpen\nClosing\nClosed" },
	]
};
