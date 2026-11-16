# RMS Management interface — 2026-11-09

The native administration area now uses RMS's dark green and citrus identity, with a full-width working canvas and a compact workspace navigator. The same shell serves the existing ERP workspaces, lists, forms and reports. It does not introduce a parallel application or change document permissions, database structure or business operations.

## Implementation

- `rms/public/js/rms_desk.js` reads the native, permitted workspace list (`frappe.workspace.all_pages`, with the v15 boot fallback). It preserves workspace hierarchy and private routes, supports translated labels and workspace search, and never injects dynamic workspace labels as HTML.
- Desktop navigation is 232px wide and collapses to 76px. Below 1200px it becomes an overlay drawer. The drawer supports Escape, focus containment, backdrop dismissal, native global search shortcuts and route dismissal. Height-only changes from a mobile keyboard keep the drawer open.
- Navigation respects the native Workspace loading lock so consecutive selections cannot overlap native page rendering. The original workspace editor remains available; its sidebar returns while editing.
- `rms/public/css/rms_desk.css` styles the native toolbar, workspaces, lists, forms, child tables, dialogs and reports. It offsets the actual `.main-section` because v15 explicitly resets body padding. Mobile filters use two columns from 360–767px, while native report grids retain their horizontal scrolling and accounting columns.
- RTL uses logical positioning and the native Arabic dictionary. Dark mode keeps native semantic status colors. The custom drawer respects reduced motion and uses larger touch targets and 16px search inputs on touch devices.
- POS, table management and kitchen display remain outside the Management shell. Saved carts and order data are not cleared. The existing one-time stale Page-script cache cleanup remains narrowly scoped.
- The previous welcome called a v16-only toast API on a v15 installation. It now uses the supported native alert on v15, escapes user names, follows the selected language, and appears once per document load.
- Hooks version the final plain assets as `desk-a-80` (JS) and `desk-a-15` (CSS); the site's cache was cleared. No bundled asset rebuild or migration is required.

## Verification

- All 15 POS JavaScript suites, the approval notification suite and the new Management suite passed (17 suites).
- The Management suite covers permitted/hidden workspaces, private routes, fullscreen-page isolation, document names matching page slugs, saved-cart preservation, escaped welcome content, supported alert APIs, native modal Escape behavior and keyboard focus containment.
- 20 browser checks passed, covering real workspace navigation, hierarchy, search, collapse, native global search, workspace Edit/Discard, product list filters, the native Add action without saving, a saved Store form, reporting, mobile filters, keyboard navigation, POS isolation and returning to Management.
- Responsive checks used widths 320, 390, 768, 1024, 1194, 1366 and 1600px. Page-level horizontal overflow was checked; report tables retain their own scrolling.
- Native Stock Ledger rendered 34 rows and 13 filters. Its layout passed additional checks at 320, 390, 768, 1024 and 1600px.
- Arabic/RTL desktop and mobile search/navigation, dark mode and reduced motion passed. The RTL preview used native RTL CSS and Arabic translations in the browser without changing the user's saved language.
- Chromium device emulation passed for iPhone 13, iPad generation 7 and a 1366px iPad Pro landscape viewport, including touch targets, input size and drawer behavior. Physical Safari hardware was not available.
- No uncaught JavaScript errors occurred in successful final browser runs. No existing documents were saved and no financial transactions were performed. The isolated preview session was removed after verification.

Screenshots and detailed results: `/home/xxx/outputs/rms-management/`. Consolidated results are in `docs/verification/rms-management-2026-11-09.json`.

## Existing issue found outside this UI change

`RMS POS Sales Summary` currently fails to import `rms.rms.report.rms_pos_sales_summary`; its source folder is `pos_sales_summary`. This backend naming issue predates the UI change and was not changed here. Report layout verification therefore also used the working native Stock Ledger report.
