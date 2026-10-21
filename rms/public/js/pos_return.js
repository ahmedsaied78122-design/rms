frappe.ui.form.on("POS Return", {
	refresh(frm) {
		if (frm.doc.status !== "Pending Approval" || !["POS Manager", "System Manager"].some((role) => frappe.user.has_role(role))) {
			return;
		}
		frm.add_custom_button(__("Approve Return"), () => {
			frappe.call({
				method: "rms.api.pos.approve_pos_return",
				args: { return_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Creating Credit Note and stock receipt…"),
			}).then(() => frm.reload_doc());
		}, __("Actions"));
		frm.add_custom_button(__("Reject Return"), () => {
			frappe.prompt({
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Rejection Reason"),
				reqd: 1,
			}, ({ reason }) => frappe.call({
				method: "rms.api.pos.reject_pos_return",
				args: { return_name: frm.doc.name, reason },
				freeze: true,
			}).then(() => frm.reload_doc()), __("Reject POS Return"), __("Reject"));
		}, __("Actions"));
	},
});
