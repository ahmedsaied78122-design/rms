app_name = "rms"
app_title = "RMS"
app_publisher = "RMS Project"
app_description = "Integrated enterprise resource planning"
app_email = ""
app_license = "MIT"
required_apps = ["erpnext", "arab_streaming"]
setup_wizard_requires = "assets/rms/js/rms_setup_wizard.js"
setup_wizard_success = "rms.onboarding.master_setup_success"
override_whitelisted_methods = {
	"frappe.desk.page.setup_wizard.setup_wizard.setup_complete": "rms.onboarding.complete_master",
	"arab_streaming.api.connection.branches": "rms.onboarding.master_choices",
}
arab_streaming_after_initial_sync = ["rms.onboarding.finish_slave"]
arab_streaming_connection_target_providers = ["rms.streaming_targets.provide"]
arab_streaming_defer_initial_links = ["rms.onboarding.defer_initial_links"]
app_logo_url = "/assets/rms/images/rms-mark.svg"
app_home = "/rms"

add_to_apps_screen = [
	{
		"name": "rms",
		"logo": "/assets/rms/images/rms-mark.svg",
		"title": "RMS",
		# Desk routes are validated as Workspaces by the app launcher.
		# Use our entry page so Point of Sale (a Page) is not replaced by a workspace.
		"route": "/rms",
		"sequence_id": 10,
	}
]

app_include_js = [
	"/assets/rms/js/rms_reporting.js?v=analytics-4",
	"/assets/rms/js/rms_management_workspace.js?v=studio-10",
	"/assets/rms/js/rms_desk.js?v=desk-a-101",
	"/assets/rms/js/rms_form_experience.js?v=forms-6",
	"/assets/rms/js/approval_notifications.js?v=4",
]
app_include_css = [
	"/assets/rms/css/rms_desk.css?v=desk-a-16",
	"/assets/rms/css/point_of_sale.css?v=pos-a-109",
	"/assets/rms/css/rms_management_studio.css?v=studio-16",
	"/assets/rms/css/rms_form_experience.css?v=forms-5",
	"/assets/rms/css/rms_reporting.css?v=analytics-4",
]
update_website_context = "rms.interface_preferences.website_context"

after_migrate = ["rms.onboarding.install_defaults", "rms.setup.ensure_streaming_reference_roles", "rms.setup.ensure_stock_type_translation", "rms.setup.ensure_pos_roles", "rms.branding.apply_branding", "rms.analytics.install.ensure_analytics", "rms.streaming_policy.ensure_defaults", "rms.streaming_targets.install", "rms.onboarding.preserve_pending_slave_setup"]
after_install = ["rms.onboarding.install_defaults", "rms.setup.ensure_streaming_reference_roles", "rms.setup.ensure_stock_type_translation", "rms.branding.apply_branding", "rms.streaming_policy.ensure_defaults", "rms.streaming_targets.install"]

# Native controllers generate prices, audit journals and print jobs locally.
arab_streaming_local_doctypes = ["Approval Challenge", "Print Dispatch Job", "RMS Sync Event", "RMS Sync Settings", "Item Price", "Loyalty Point Entry", "POS Invoice Merge Log"]
# Optional HRMS/Lending extensions belong to those apps' local installations.
# The RMS release contains ERPNext, Arab Streaming and RMS only.
arab_streaming_local_fields = {
	"POS Return": ["approval_challenge"],
	"Company": [
		"default_employee_advance_account", "default_expense_claim_payable_account",
		"default_payroll_payable_account", "custom_hr_damage_component",
		"custom_hr_damage_receivable", "custom_hr_internal_enabled",
		"custom_hr_require_payroll_review", "custom_hr_saudi_policy_enabled",
		"custom_hr_sick_deduction_component", "custom_hr_sick_leave_type",
		"collection_offset_logic_based_on", "collection_offset_sequence_for_settlement_collection",
		"collection_offset_sequence_for_standard_asset", "collection_offset_sequence_for_sub_standard_asset",
		"collection_offset_sequence_for_written_off_asset", "days_past_due_threshold",
		"interest_day_count_convention", "irac_provisioning_configuration",
		"loan_classification_ranges", "loan_restructure_limit",
		"min_days_bw_disbursement_first_repayment", "watch_period_post_loan_restructure_in_days",
	],
	"Item Default": [
		"default_receivable_account", "default_suspense_account",
		"default_waiver_account", "default_write_off_account",
	],
	"Customer": ["is_npa"],
}
arab_streaming_branch_resolvers = {"rms_store": "rms.streaming_policy.resolve_branch", "rms_operation_store": "rms.streaming_policy.resolve_operation_branch"}
arab_streaming_managed_branch_routing = True
arab_streaming_after_apply = ["rms.streaming_policy.remember_branch"]
arab_streaming_default_providers = ["rms.streaming_policy.connection_defaults"]

from rms.streaming import doc_events as rms_sync_doc_events

doc_events = {**rms_sync_doc_events, "POS Closing Entry": {
	"on_change": "rms.streaming_closing.capture_native_change",
}, "POS Invoice": {
	"on_change": "rms.streaming_closing.capture_native_change",
	"before_validate": "rms.streaming_closing.preserve_invoice_rounding",
}, "Sales Invoice": {
	"before_validate": ["rms.pos_rounding.preserve_consolidated_pos_no_rounding", "rms.stock.prevent_duplicate_return_stock"],
}}

from rms.naming import TITLE_MASTERS as _rms_title_masters

for _doctype in _rms_title_masters:
	doc_events[_doctype] = {
		**doc_events.get(_doctype, {}),
		"autoname": "rms.naming.name_from_title",
		"before_validate": "rms.naming.validate_display_title",
	}

extend_doctype_class = {
	"POS Invoice": "rms.pos_rounding.POSInvoiceRoundingMixin",
}

# Frappe 15 does not implement extend_doctype_class. Use its supported override
# mechanism so recalculation during invoice validation retains the same rounding.
import frappe as _frappe

if int(_frappe.__version__.split(".")[0]) < 16:
	override_doctype_class = {"POS Invoice": "rms.pos_invoice.RMSPOSInvoice", "POS Closing Entry": "rms.streaming_closing.RMSPOSClosingEntry"}

override_doctype_class = {
	**globals().get("override_doctype_class", {}),
	"Company": "rms.setup_company.RMSSetupCompany",
	"Account": "rms.setup_company.RMSSetupAccount",
	"Cost Center": "rms.setup_company.RMSSetupCostCenter",
}

# Transaction Deletion Record must keep RMS catalog and setup records intact.
company_data_to_be_ignored = [
	"Selling Product",
	"Product Category",
	"Restaurant Brand",
	"Store",
	"Store Menu",
	"Store Brand Assignment",
	"Store Working Hour",
	"Store Order Type Tax",
	"Store User Assignment",
	"Dining Area",
	"Dining Table",
	"Preparation Area",
	"Modifier Group",
	"Order Type",
	"Order Type Account Mapping",
	"POS User",
	"POS User Store",
	"POS User Brand",
	"POS User Preparation Area",
	"POS User Order Type",
	"Expense Category",
	"Print Device",
	"RMS Sync Settings",
]

doctype_js = {
	"Store": "public/js/store_streaming.js",
	"Approval Challenge": "public/js/approval_challenge.js",
	"POS User": "public/js/pos_user.js",
	"Selling Product": "public/js/selling_product.js",
	"POS Return": "public/js/pos_return.js",
	"Shift Expense": "public/js/shift_expense.js",
}

permission_query_conditions = {
	"POS Return": "rms.api.pos.get_pos_return_permission_query",
	"Shift Expense": "rms.api.pos.get_shift_expense_permission_query",
	"Approval Challenge": "rms.api.pos.get_approval_challenge_permission_query",
	"Print Dispatch Job": "rms.api.printing.get_print_dispatch_job_permission_query",
}

has_permission = {
	"POS Return": "rms.api.pos.has_pos_return_permission",
	"Shift Expense": "rms.api.pos.has_shift_expense_permission",
	"Approval Challenge": "rms.api.pos.has_approval_challenge_permission",
	"Print Dispatch Job": "rms.api.printing.has_print_dispatch_job_permission",
}

