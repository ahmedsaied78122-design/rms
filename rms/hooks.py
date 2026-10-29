app_name = "rms"
app_title = "RMS"
app_publisher = "RMS Project"
app_description = "Restaurant and retail operations"
app_email = ""
app_license = "MIT"
required_apps = ["erpnext"]
app_logo_url = "/assets/rms/images/rms-portrait.jpg"
app_home = "/app/point-of-sale"

add_to_apps_screen = [
	{
		"name": "rms",
		"logo": "/assets/rms/images/rms-portrait.jpg",
		"title": "RMS",
		"route": "/app/point-of-sale",
		"sequence_id": 10,
	}
]

app_include_js = ["/assets/rms/js/rms_desk.js?v=desk-a-35"]
app_include_css = [
	"/assets/rms/css/rms_desk.css?v=desk-a-8",
	"/assets/rms/css/point_of_sale.css?v=pos-a-57",
]
web_include_css = ["/assets/rms/css/rms_login.css"]

after_migrate = "rms.setup.ensure_pos_roles"

from rms.streaming import doc_events as rms_sync_doc_events

doc_events = rms_sync_doc_events

extend_doctype_class = {
	"POS Invoice": "rms.pos_rounding.POSInvoiceRoundingMixin",
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

