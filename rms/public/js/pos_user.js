frappe.ui.form.on("POS User", {
	user(frm) {
		const selectedUser = frm.doc.user;
		frm.set_value("roles_summary", "");
		if (!selectedUser) return;

		frm.set_value("roles_summary", __("Loading roles…"));
		frappe.call({
			method: "rms.api.pos.get_pos_user_role_summary",
			args: { user: selectedUser },
			callback: (response) => {
				if (frm.doc.user === selectedUser) {
					frm.set_value("roles_summary", response.message || __("No roles assigned"));
				}
			},
			error: () => {
				if (frm.doc.user === selectedUser) {
					frm.set_value("roles_summary", __("Roles are unavailable. Check the selected user and your POS User access."));
				}
			},
		});
	},
});
