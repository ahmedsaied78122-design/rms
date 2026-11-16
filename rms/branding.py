import frappe
from frappe import _


RMS_LOGO = "/assets/rms/images/rms-mark.svg"
RMS_FAVICON = "/assets/rms/images/rms-favicon.png"


def apply_branding():
	"""Keep the public sign-in and Desk identity consistent with the register."""
	for doctype, values in {
		"Website Settings": {"app_name": "RMS", "app_logo": RMS_LOGO,
			"favicon": RMS_FAVICON, "splash_image": RMS_LOGO,
			"banner_image": RMS_LOGO, "footer_logo": RMS_LOGO, "footer_powered": "RMS"},
		"System Settings": {"app_name": "RMS"},
		"Navbar Settings": {"app_logo": RMS_LOGO},
	}.items():
		doc = frappe.get_single(doctype)
		changed = False
		for field, value in values.items():
			if doc.get(field) != value:
				doc.set(field, value)
				changed = True
		if doctype == "Navbar Settings":
			for item in doc.help_dropdown:
				framework_link = any(word in (item.route or "").lower() for word in ("frappe", "erpnext"))
				framework_about = item.action == "frappe.ui.toolbar.show_about()"
				if (framework_link or framework_about) and not item.hidden:
					item.hidden = 1
					changed = True
		if changed:
			doc.save(ignore_permissions=True)


def website_context(context):
	context.app_name = "RMS"
	context.favicon = RMS_FAVICON
	context.splash_image = RMS_LOGO
	# Keep the launcher useful without presenting the accounting engine as a
	# separate product. Routes and permissions continue to come from the engine.
	apps = list(context.get("apps") or [])
	boot = context.get("boot") or {}
	if isinstance(boot, dict):
		apps.extend((boot.get("apps_data") or {}).get("apps") or [])
	for app in apps:
		if app.get("name") == "erpnext":
			app["title"] = _("Management")
			app["logo"] = RMS_LOGO
