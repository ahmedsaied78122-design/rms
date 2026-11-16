# RMS sign-in and application identity

The launcher, favicon, splash and toolbar now use the citrus R mark from the
register. The login page replaces the portrait and broken side-by-side form with
a dark green product panel and a separate sign-in area. Labels remain visible;
field icons and the password toggle have their own space. Arabic uses a mirrored
layout, and narrow screens prioritize the form.

The tagline is “A complete ERP. Everything in one place.” / «نظام ERP متكامل.
كل شغلك في مكان واحد.» Login, recovery and email-link pages display RMS branding. The
accounting entry in the launcher is labelled “Management” / «الإدارة», with its
existing route and permissions. Standard framework promotion/help links are
hidden; keyboard shortcuts remain available.

`rms/www/login.html` extends the native login template and scripts. Its controller
delegates authentication context, providers, MFA settings and existing-session
redirects to the standard controller. Language links preserve the destination as
a validated local path, including when the site runs behind an HTTPS proxy. No
authentication settings were changed.

`rms.branding.apply_branding` updates identity fields in Website Settings, System
Settings and Navbar Settings. It is idempotent and runs after installation and
migration. Source licences and framework dependencies remain unchanged.

Validation includes three controller/security tests and native Chromium checks
at 1600, 1024, 390 and 320 pixels: English/Arabic, visible labels, icon alignment,
keyboard password visibility, recovery/email-link pages, invalid-login feedback
and actual credential authentication with a temporary cashier account. The test
account and sessions were removed, and no email was sent. Launcher and Desk logo
metadata were checked after authentication. A previously observed Desk console
error (`frappe.ui.toast is not a function`) still occurs on `/app`; the login
pages have no JavaScript errors. This branding change does not alter Desk toast
handling.

Screenshots and browser results are in `/home/xxx/outputs/rms-login`. The recorded
checks are in `docs/verification/2026-11-09-rms-login-branding.json`.

The login now presents the full ERP scope rather than a restaurant-only product.
Fifteen domain labels cover finance, HR, manufacturing, warehouses, supply chain,
sales/CRM, purchasing, projects, assets/maintenance, quality, support,
integrations, POS, analytics and workflows. An abstract business dashboard
replaces the food-menu illustration. On short desktop layouts the decorative
preview is omitted to keep the complete list visible; mobile uses a collapsed
module overview below the form. These are product-description changes, with no
module installation, feature activation, permission or route changes.

Updated screenshots and checks are in `/home/xxx/outputs/rms-login-erp` and
`docs/verification/2026-11-09-rms-erp-login-copy.json`.
