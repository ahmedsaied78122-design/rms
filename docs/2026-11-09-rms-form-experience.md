# RMS custom form experience — 2026-11-09

The work covers all 56 DocTypes in the RMS module: 24 parent forms and 32 child tables. The supplied spreadsheet, selected live reference metadata/forms and selected archive definitions were used to understand functional relationships and naming differences. No reference implementation, styling or assets were copied or executed. The user-provided archive remains intact in `arabista/`, which is now excluded from Git. No additional DocType was introduced.

The only new business field is the explicitly approved `Modifier Group.max_selections`. Other added fields are Section/Column Break layout controls. Existing business field names, links, identifiers, stored Select values and data remain. The Arabic review inventory is [rms-form-review-2026-11-09.csv](verification/rms-form-review-2026-11-09.csv).

## Form behavior

- The shared form experience uses RMS colors and native controls. It provides a short purpose statement, zero-safe guidance for parent required fields and keyboard-accessible section navigation. Saving, links, row editing and existing form scripts continue through the native framework.
- Essential fields appear first in balanced columns. Larger tables occupy full-width sections. Empty optional sections are collapsed; existing configuration opens automatically. Navigation opens a collapsed section and respects reduced-motion preferences.
- The stock/recipe/variation paths follow the existing controller rules. Turning off a populated recipe preserves its rows and explains how to proceed. Disabling group collapse clears the incompatible collapsed-by-default flag.
- Printer method controls show and require only relevant fields. Product option rows and recipe requirements, category item-group requirements and manual-discount controls follow their controlling flags. Closed cashier balances remain visible and read-only. Submitted return requests and existing shift expense inputs reflect their server workflow locks.
- Company, store, parent-group and assigned-store relationships constrain link choices. The new read-only scoped search endpoint restricts targets to four named master types; store and target queries apply native permissions. Child scope is derived only from permission-filtered stores, with bounded pagination. Nothing supplied by the client can expand this to an arbitrary DocType or company.
- Kitchen viewing and action permissions are independent in the existing RMS API. Action settings therefore remain visible instead of being hidden under the view checkbox. No role assignments or effective permission flags were changed.
- Child grid columns fit the native ten-column limit. Detailed fields remain in the row editor. Phones use one form column and local table scrolling, preserving the page width. Labels, choices, descriptions, new guide text and setup-controller validation messages are covered in Arabic while stored values stay unchanged.

## Modifier maximum

For multiple-choice groups, `0` preserves the previous unlimited maximum; single-choice groups still allow one. Negative maxima, maxima below a nonzero minimum and a single-choice maximum above one are rejected. Product-level required/optional overrides still determine the minimum independently.

The configuration API includes the effective maximum. Both POS selection flows disable unchecked choices once the limit is reached and allow replacement after deselecting an item. Direct Add actions revalidate. Order validation enforces the maximum on the server, so client manipulation cannot bypass it. Unchanged choices on an existing saved order retain the same compatibility policy already used for minimum changes. The local catalog journal now includes selection limits and product requirement overrides; no remote transport was added.

Group rendering also honors Allow Collapse and Collapsed By Default. Non-collapsible groups remain expanded. Required groups start open; the configuration description explains this behavior.

## Verification and application

- All 56 source definitions passed checks for business-field preservation, field order, valid link targets/filter fields/fetch paths, bounded grid columns and unchanged source permission declarations.
- Real native bundles rendered all 24 forms and all 32 child grids using local fixture data and mocked RPC. Conditional visibility/requiredness, parent-based native link filtering and key forms in Arabic/English and light/dark modes passed at widths 320, 390, 768, 1024 and 1500px. These are viewport checks, not physical device certification.
- A real native POS dialog blocked the third choice at a maximum of two, permitted replacement, rejected a forced over-limit Add and accepted the valid selection. No actual sale, refund, stock movement, print job, message or test account was created.
- 19 JavaScript suites and 89 initialized isolated Python tests passed, covering scope permissions, limits, serialization, data retention and existing POS behavior.
- DocType metadata was reloaded on the RMS site, with a pre-task metadata backup retained outside the product. Effective live field layout/dependency properties match the reviewed definitions. The approved maximum column exists. Runtime role permissions were compared against the pre-task snapshot for all 56 types.
- The existing Shift Expense source declaration already differed from the live site on two submit flags. Importing metadata exposed that difference; the two live flags were restored to their pre-task values. The unrelated existing source permission declaration was preserved. Future metadata imports should account for that pre-existing difference.
- No business records were edited as part of testing or layout application. Tests used local data and mocked persistence; live metadata inspection was read-only. Reference credentials and temporary reference material were removed from task-created temporary files after review.

Final includes: `rms_form_experience.js?v=forms-2`, `rms_form_experience.css?v=forms-2`, POS stylesheet `pos-a-101`. The site cache was cleared. Browser evidence is in `/home/xxx/outputs/rms-form-experience/` and [the verification JSON](verification/rms-form-experience-browser-2026-11-09.json).
