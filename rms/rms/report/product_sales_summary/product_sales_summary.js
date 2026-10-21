frappe.query_reports["RMS Product Sales Summary"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.month_start() },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today() },
		{ fieldname: "store", label: __("Store"), fieldtype: "Link", options: "Store", get_query: () => ({ filters: { enabled: 1 } }) },
		{ fieldname: "restaurant_brand", label: __("Brand"), fieldtype: "Link", options: "Restaurant Brand", get_query: () => ({ filters: { enabled: 1 } }) },
		{ fieldname: "selling_product", label: __("Selling Product"), fieldtype: "Link", options: "Selling Product", get_query: () => ({ filters: { enabled: 1, has_options: 0 } }) },
	]
};
