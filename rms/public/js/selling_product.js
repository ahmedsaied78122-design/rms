function encodeOrderTypeName(value) {
	const bytes = new TextEncoder().encode(value);
	const binary = Array.from(bytes, (byte) => String.fromCharCode(byte)).join("");
	return btoa(binary).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
}

function escapeOptionLabel(value) {
	return value.replace(/%/g, "%25").replace(/,/g, "%2C");
}

frappe.ui.form.on("Selling Product", {
	refresh(frm) {
		frm.__rmsOrderTypeOptionsPromise ||= frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Order Type",
				fields: ["name", "title"],
				filters: { enabled: 1 },
				order_by: "sequence_id asc, title asc",
				limit_page_length: 500,
			},
		}).then(({ message = [] } = {}) => {
				const grid = frm.fields_dict.additional_recipe?.grid;
				if (!grid) return;

				const options = message.map((row) => ({
					label: `${escapeOptionLabel(row.title || row.name)} [${escapeOptionLabel(row.name)}]`,
					value: encodeOrderTypeName(row.name),
				}));
				grid.update_docfield_property("order_types", "options", options);
				grid.refresh();
			});
	},
});
