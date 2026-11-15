# RMS form interaction correction — 2026-11-10

The earlier form guide scrolled between simultaneously visible sections. It did not implement the user's requested one-section-at-a-time interaction. The earlier browser review primarily exercised Layout rendering and did not run the native saved-form cleanup that hides an autoname field. This follow-up corrects those gaps.

## Form sections

All 24 RMS parent forms now render one available section at a time. The first section opens initially; the existing top buttons switch panels and retain unsaved model values. Native hidden/dependent and empty sections stay excluded. The selected panel opens its collapsed body. Keyboard navigation supports arrows/Home/End, with RTL-aware arrow direction, tab/tabpanel associations and a single selected state. Desktop navigation wraps, while phone navigation scrolls horizontally. Hover is distinct from selection.

Required-field guidance checks eligible fields in other presentation-hidden panels. A per-form bridge reveals the owning section before the native `scroll_to_field` method runs, so native mandatory validation can bring the user to a missing field or table. Saving and server validation remain native. Grid refresh runs on panel changes rather than on each keystroke.

## Editable names

Twelve title-based RMS masters previously used `autoname=field:title`. Native Form cleanup hides that field on saved records, and server `_sync_autoname_field` replaces edits with the existing ID. Those masters now use a small RMS naming hook for initial name assignment, with the same entered-title creation convention, and separate subsequent display-title editing from the stored link identity. Existing records are not renamed or migrated. Link fields display the current title.

Titles are trimmed and blank names rejected; numeric zero is a valid display name. Existing doctype-specific validation and local journal hooks are retained. When a Selling Product title changes, the linked Item's `item_name` changes in the existing update flow; product ID, Item code and references remain. Unrelated product edits do not overwrite a separately maintained stock label.

This behavior was checked against the reference sheet's Menu Product metadata (`By script`), without copying its implementation.

## Child grids

Parent form spacing no longer changes inline grid-control margins, checkbox placement or cell heights. Header text can wrap; static and editable cell geometry align. Expanded row forms keep their own field spacing. On a phone, horizontal scrolling is contained within the grid container; the expanded row fits the viewport and hides sibling rows while editing. Closing it restores the native list without page overflow.

Fourteen child schemas received deliberate visible-column allocations: primary names/links get more width, sorting flags get less, and secondary cost/technical fields remain available in the expanded row editor. No field was removed. Every grid retains the native ten-column budget. Native editing, row addition and save serialization were exercised with populated rows rather than empty placeholders.

## Application and validation

- Naming metadata and grid display properties were applied directly, with a backup in `/tmp/rms-before-form-repair.json`, without reimporting DocPerms or business records. Effective DocPerm flags remain equal to the prior snapshot.
- Metadata `modified` timestamps were advanced for affected definitions and owning forms. Native `getdoctype` was verified to return fresh metadata for an old cached timestamp, preventing old browser definitions from hiding the name or retaining old columns.
- Raw asset hooks use `rms_form_experience.js?v=forms-4` and `rms_form_experience.css?v=forms-4`. Site caches were cleared. The existing development service reloads Python changes.
- Native Form cleanup, Layout, model watchers, ScriptManager, controls, required-field checks and save callbacks were run with locally mocked RPC/persistence. A saved Product name was edited, saved and reloaded with its new title and original product/Item identities. A populated modifier price was edited, another row added and both changes serialized through native save. Native mandatory validation opened a hidden required pane.
- All 24 parent forms showed one panel. Arabic/English, light/dark and widths 320/390/768/1024/1500 passed. Phone row open/close preserved page width.
- All 32 child grid schemas were rendered populated. Twenty-nine were reached through their actual root-form/conditional states. Three legacy schemas not referenced by a current Table field were exercised as direct native grid fixtures (`POS Order Item Modifier`, `POS Order Item Recipe Line`, `Order Type MultiSelect Option`); this does not claim that they have standalone application screens.
- Python verification covered the existing read-only suites, setup/workspace contracts, display-name hooks, stock-label synchronization, recipe behavior and non-writing naming checks. Real database counter and Item/Item Price creation integration tests were not run against live business data. JavaScript suites cover pane isolation, selection state, required fields in hidden panes and the native reveal bridge, alongside existing POS behavior.

The UI persistence test used a local in-memory RPC store. No live sales, stock/accounting movements, production product names, test users or authenticated browser sessions were created or edited for verification. Actual hardware/external services are outside these UI checks.

Browser evidence: [rms-form-repair-browser-2026-11-10.json](verification/rms-form-repair-browser-2026-11-10.json). Screenshots: `/home/xxx/outputs/rms-form-repair/`.
