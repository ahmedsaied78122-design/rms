# RMS Business Suite presentation — 2026-11-09

This replaces the initial Management theme with a distinct RMS workspace presentation. The working screens retain their existing data, permission checks and controllers; the visible layout is no longer the standard workspace/editor layout.

## What changed

- An inset, rounded navigation panel with RMS branding, a dedicated icon catalog, grouped business modules, hierarchy, local module search, selected states, mini navigation and a signed-in account card. Every destination comes from the user's existing permitted workspace list.
- A branded command bar retaining the actual native search input, command suggestions, notifications, profile and logout actions. On phones, search opens in a dedicated panel with its own backdrop; Ctrl/Cmd+G, Enter, Escape, route selection and notification dismissal work with the existing command engine.
- A separate workspace canvas with an RMS introduction, actual module count, date, permission-controlled layout customization actions and sections for metrics, charts, shortcuts, records/reports and activity.
- Existing widget DOM nodes are moved into the new layout, rather than cloned or re-created with fabricated values. Comment markers preserve their original positions. Original nodes and accessibility attributes are restored before workspace editing and route changes. Disposed widgets are removed without leaving duplicated or ghost cards. Custom content remains available.
- Chart presentation uses an RMS palette, distinct category colors, red warning series, rounded bars, region fills and new panels. Dataset objects, chart types, currency formatting, configured line/stack options and callbacks are preserved. SVG updates render atomically to prevent canvas replacement errors during rapid resizing/orientation changes. No chart or dashboard configuration is saved by the presentation layer.
- Standard onboarding is omitted from the everyday overview. Framework product names in interface guidance are replaced with RMS. Stored record names, document values, source notices and license files are untouched.
- The new visual system also covers record headings, lists, filter panels, forms, tabs, child grids, report grids, menus and dialogs. Dark mode and reduced motion are supported.
- Phones and tablets use an overlay module panel. Touch targets, 16px touch inputs and the visual viewport keep search and navigation usable above the on-screen keyboard. Height-only viewport changes keep search/drawers open. RTL uses logical layout properties.

## Source and deployment

- `rms/public/js/rms_management_workspace.js`: workspace presentation and scoped chart subclass.
- `rms/public/js/rms_desk.js`: navigation, header, search and lifecycle integration.
- `rms/public/css/rms_management_studio.css`: the new design system, layered after existing Desk/POS styles and scoped to Management.
- `rms/translations/ar.csv`: Arabic interface labels.
- `rms/public/js/test_rms_management_workspace.js`: chart and reversible ownership tests.

The final hooks reference workspace JS `studio-5`, shell JS `desk-a-85` and studio CSS `studio-5`. Static assets are served directly; site caches were cleared. A browser refresh loads the new asset versions. POS, tables and kitchen display retain their existing full-screen presentation.

## Validation

- All 18 JavaScript suites passed: 15 POS suites, approval notifications, Management shell and the new workspace presentation tests.
- 20 core browser checks passed for hierarchy, permission-derived navigation, search, collapse, native Edit/Discard, list filters, Add without saving, a saved Store form, reporting, mobile filters, keyboard focus, POS isolation and returning to Management.
- 20 further interaction checks passed for reversible widget ownership, no duplicate widgets, branding, chart actions/filters, metric keyboard routes, interface guidance, Home overview and responsive command search.
- Three dedicated search checks passed for desktop Enter, phone Ctrl+G/Enter navigation, and opening notifications while phone search is open.
- Five Arabic checks passed with a real, isolated Arabic-language user: actual RTL assets and translations, permitted navigation and widgets, module search, global command search, reduced motion and dark mode. Its required business roles were assigned only to this temporary fixture, and the fixture/user/session were removed afterward. No welcome email was sent.
- Touch/device emulation passed for iPhone 13, iPad generation 7 and a 1366px iPad Pro landscape viewport. Checked widths include 320, 390, 600, 601, 768, 810, 1024, 1194, 1366 and 1600px. Native report tables retain their own horizontal scrolling while page-level overflow remains constrained.
- Final successful browser runs had no uncaught JavaScript errors. No financial transactions or existing business records were saved. The separate Administrator preview session was removed after verification.

Screenshots and detailed results are in `/home/xxx/outputs/rms-studio/`; consolidated results are in `docs/verification/rms-studio-2026-11-09.json`. Device checks used Chromium touch/user-agent emulation; physical Safari hardware was not available. The previously documented RMS POS Sales Summary backend naming issue is outside this presentation change; report verification used the working Stock Ledger report.
