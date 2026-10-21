frappe.ui.form.on("Shift Expense", {
	refresh(frm) {
		const roles = frappe.user_roles || [];
		if (frm.doc.status !== "Pending Approval" || frm.doc.owner === frappe.session.user ||
			!(roles.includes("POS Manager") || roles.includes("System Manager"))) return;
		frm.add_custom_button(__("Issue Approval Code"), async () => {
			try {
				const result = await frappe.call({
					method: "rms.expenses.issue_shift_expense_approval_code",
					args: { expense_name: frm.doc.name }
				});
				const code = result.message;
				const dialog = new frappe.ui.Dialog({
					title: __("One Time Expense Approval Code"),
					fields: [
						{ fieldtype: "Data", fieldname: "code", label: __("Share this code with the cashier"), read_only: 1, default: code.code },
						{ fieldtype: "Datetime", fieldname: "expires_at", label: __("Expires At"), read_only: 1, default: code.expires_at }
					],
					primary_action_label: __("Done"), primary_action: () => dialog.hide()
				});
				dialog.show();
			} catch (error) { frappe.msgprint(error.message || __("Could not issue an approval code.")); }
		}, __("Approval"));
		frm.add_custom_button(__("Reject Expense"), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Reject Shift Expense"),
				fields: [{ fieldtype: "Small Text", fieldname: "reason", label: __("Reason"), reqd: 1 }],
				primary_action_label: __("Reject"),
				primary_action: async ({ reason }) => {
					try {
						await frappe.call({ method: "rms.expenses.reject_shift_expense", args: { expense_name: frm.doc.name, reason } });
						dialog.hide();
						await frm.reload_doc();
					} catch (error) { frappe.msgprint(error.message || __("Could not reject the expense.")); }
				}
			});
			dialog.show();
		}, __("Approval"));
	}
});
