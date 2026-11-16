"""RMS interface preferences, scoped to the signed-in user's own language."""
import frappe
from frappe import _

from rms.branding import website_context as brand_website_context

RMS_LOADING = "/assets/rms/images/rms-loading.svg"


def website_context(context):
	brand_website_context(context)
	context.splash_image = RMS_LOADING


@frappe.whitelist(methods=["POST"])
def set_language(language):
	"""A language switch cannot select another user or modify other preferences."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Please sign in to change your language."), frappe.PermissionError)
	if language not in ("ar", "en"):
		frappe.throw(_("Choose Arabic or English."), frappe.ValidationError)
	frappe.db.set_value("User", user, "language", language, update_modified=False)
	frappe.clear_cache(user=user)
	return {"language": language}
