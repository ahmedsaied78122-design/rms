from urllib.parse import urlencode, urlsplit, urlunsplit

import frappe
from frappe import _
from frappe.www.login import get_context as get_standard_login_context, sanitize_redirect

from rms.branding import RMS_LOGO


no_cache = True
sitemap = 0

ERP_MODULES = (
	"Accounting & Finance", "Human Resources", "Manufacturing",
	"Inventory & Warehouses", "Supply Chain", "Sales & CRM",
	"Purchasing", "Projects", "Assets & Maintenance",
	"Quality Management", "Support & Service", "Integrations",
	"Point of sale", "Reports & Analytics", "Workflows & Approvals",
)


def get_context(context):
	# Retain the standard authentication, redirect validation and provider setup.
	get_standard_login_context(context)
	context.update({
		"app_name": "RMS", "logo": RMS_LOGO, "title": _("Sign in to RMS"),
		"no_header": True, "show_footer_on_login": False,
		"login_name_placeholder": _("Enter your login ID"),
		"rms_direction": "rtl" if frappe.local.lang in ("ar", "he", "fa", "ps") else "ltr",
		"rms_erp_modules": ERP_MODULES,
	})
	redirect = sanitize_redirect(frappe.local.request.args.get("redirect-to"))
	if redirect:
		target = urlsplit(redirect)
		# Keep navigation on the current HTTPS origin behind a reverse proxy.
		redirect = urlunsplit(("", "", "/" + target.path.lstrip("/"), target.query, target.fragment))
	base = {"redirect-to": redirect} if redirect else {}
	context.rms_language_urls = {
		lang: "/login?" + urlencode({**base, "_lang": lang}) for lang in ("en", "ar")
	}
	return context
