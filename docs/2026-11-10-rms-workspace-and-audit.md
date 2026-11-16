# RMS Management workspace and functional review — 2026-11-10

The Management workspace organizes RMS into nine native link groups with six daily shortcuts and 40 grouped links. Every one of the 24 RMS parent forms is reachable; the 32 child tables remain inside their owning forms. Related standard setup screens include POS Profile, payment methods, taxes, warehouses, accounts-related defaults, units and option attributes. The existing full ERP workspaces remain available.

The previous source workspace was an unstructured shortcut collection named الإدارة and was not installed on the current site. The installed workspace is now `Management` at `/app/management`, translated to الإدارة in Arabic. There was no existing live RMS workspace to overwrite. The source definition uses native Workspace content and links, so native role/module/page/report filtering and editing continue to apply. No user assignments or effective DocPerm flags changed; the complete DocPerm set was compared before and after application.

The screen finder searches only already-rendered native widgets and links. It supports Arabic normalization, translated titles and technical English routes, shows a result count and clears on Escape. It adds no endpoint or RPC. Native nodes are restored to their original owners when leaving or editing, and search classes are removed. It does not expand the permission-filtered link set. Group icons, balanced three/two/one-column layouts, translations, dark mode and the previously approved RMS banner are retained within the existing presentation system.

## Functional correction

Frappe parent saves run field-level child validation but do not call each child controller's custom `validate` hook. `POS User.validate_stores` now explicitly invokes the existing `POSUserStore.validate` contract for every assignment. Saving the parent therefore rejects disabled or cross-company cashier POS Profiles. Matching profiles and blank Store-default fallback remain valid. Regression cases cover the second assignment as well as the first.

Two existing field descriptions now make current behavior explicit: `Store.working_hours` is reference data and does not currently enforce order-time restrictions; `Order Type.delivery_included` marks the order type but does not implement courier assignment, zones or delivery fees. Descriptions were updated in source and live DocField metadata without reimporting role permissions or other DocTypes. Synchronization remains local capture rather than inter-site transport.

## Review scope and reference comparison

The supplied Google Sheet was read as a field/DocType inventory. It contains 966 DocTypes. Of those, 199 are specialized application/custom definitions in scope (114 standalone forms/settings and 85 child tables); all remaining 767 base definitions exist by name on RMS. Name existence alone does not establish field, permission or runtime parity. The comparison distinguishes same-name existence, functional counterparts, partial coverage, missing specialized features, and child tables to review with their parent feature.

Arabic functional summaries were derived from metadata. No proprietary implementation, styling or assets were copied. The report is evidence for selecting RMS requirements, not a certification of the reference system's runtime behavior. No new DocType or business field was introduced during this task.

`Mode of Payment Filter` is a genuine capability gap: the reference has conditions for branch, brand, order type/source and priority plus allowed payment methods. RMS currently gets methods from the cashier POS Profile. The report recommends reviewing contextual payment rules, payment reallocation, sales quantity limits, order sources, branch closure, recipe bulk updates and barcode composition before adding further models. Some requirements can extend existing RMS or standard records rather than creating duplicate DocTypes. New business capabilities await the user's selection.

## Validation

- 56 RMS definitions / 560 fields, including layout fields: field order, 181 Link/Table targets, 91 link filters, 17 fetch paths and all conditional references checked with no structural errors.
- 97 JavaScript field expressions compiled and evaluated against 2,328 representative state combinations. This verifies expression execution, not every business combination.
- 423 isolated Python tests passed: existing operational/API/report/controller coverage, new setup and native workspace permission contracts, recipe validation and non-writing naming tests. Modules ran in separate read-only database transactions with live `Document.insert/save` prohibited. The real Item/Item Price insertion and actual database counter integration tests were intentionally not run on the live site.
- 19 JavaScript suites passed, including POS behavior, form guides, chart invariance, native save ownership and Arabic search normalization.
- Actual installed native widget classes and route generation rendered the new workspace in 20 viewport/language/theme combinations (320, 390, 768, 1024 and 1500px; Arabic/English; light/dark). Search, no-results/reset, singleton/report routes, keyboard shortcut navigation, native node restoration and an already-filtered limited scope passed. This used local fixture data and mocked RPC, without a live authenticated browser session.
- The live Workspace matches the source; merged Arabic translations cover every workspace caption/description. Versioned JS/CSS assets return HTTP 200 with the new content. The development web service uses its existing automatic reloader; no bench-wide restart was needed.
- The offline comparison report was tested for 114-form / 85-child views, search, priority filtering, persistent selections, copying/fallback and viewport fit. The Excel workbook was reopened and checked for expected sheet counts and absence of formulas.

These checks do not certify live accounting postings, stock movements, physical printing, external integrations or every configured business scenario. No test users, login sessions, sales, refunds, stock movements or accounting records were created.

## Review artifacts

- [Interactive Arabic comparison and selection report](verification/rms-review-2026-11-10.html)
- [Excel workbook: comparison, priorities, children and every RMS field](verification/rms-review-2026-11-10.xlsx)
- [Reference inventory CSV](verification/rms-reference-doctypes-2026-11-10.csv)
- [Every-field audit CSV](verification/rms-field-review-2026-11-10.csv)
- [Structural audit JSON](verification/rms-field-audit-2026-11-10.json)
- [Browser evidence](verification/rms-workspace-browser-2026-11-10.json)

Additional screenshots and browser evidence are in `/home/xxx/outputs/rms-workspace-review/`. The CSV/Excel legend explains checkboxes as `1 = enabled`, `0 = disabled`; required/hidden/read-only columns use `1 = yes`, `0 = no`, with conditional expressions shown separately.
