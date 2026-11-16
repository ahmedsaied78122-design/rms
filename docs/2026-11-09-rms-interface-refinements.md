# RMS interface refinements — 2026-11-09

The selected invoice form tab and featured metric cards now use black foreground text in both themes. Featured metrics continue to follow the existing positional rule (1, 4, 7, ...); the accent is presentation, not a financial status. Card-local color variables also protect nested native titles and statistics from dark-theme white text.

A globe control beside notifications toggles Arabic/English for the signed-in user. `rms.interface_preferences.set_language` accepts authenticated POST requests and only the two supported language codes. It derives the account from the server session, accepts no target user or arbitrary fields, and updates only that account's language. Native CSRF/authentication remain in place. The client protects unsaved documents and workspace layouts, suppresses duplicate clicks, and uses native request freezing while updating/reloading. Errors leave the current page usable.

The sidebar's POS and all-apps shortcuts were removed. The account card remains. The collapsed desktop rail now contains an explicit, labelled expand control, in addition to the existing header toggle. Workspace **Edit layout** and **+ / New workspace** remain in the green workspace banner and retain native permission checks.

The welcome is always Arabic, with RTL text and escaped user names, regardless of interface language. Its corner placement follows page direction independently of the toast's Arabic text direction.

The initial Desk splash now uses a self-contained green RMS letter animation. `rms.interface_preferences.website_context` preserves the existing brand context and changes only the splash asset. The normal application logo and favicon remain unchanged. The native splash lifecycle is preserved, with no artificial loading delay. An outer reduced-motion rule supplies a static RMS asset because SVG-image documents do not reliably re-evaluate changed media preferences in every browser.

## Validation

- 18 existing/new JavaScript suites passed.
- Five isolated backend tests passed for own-account scope, Guest rejection, invalid-language rejection before writes, authenticated POST-only registration, and the splash/brand context.
- Fourteen browser-fixture checks passed using the actual native and RMS CSS plus the RMS scripts: dark/light contrast, Arabic welcome, footer removal, mini-rail expansion, language request contract and dirty-data protection, widths 320/390/768/810/1024/1366, animated loading and static reduced-motion loading.
- The browser language request was intercepted; backend tests used mocked persistence. No live account language, role, session or business record was modified for testing. No messages were sent.
- Public SVG assets loaded successfully. Syntax/formatting checks passed and the site cache was cleared. Final asset versions are shell `desk-a-87` and studio CSS `studio-8`; no service restart is required on the active development server.

Evidence: `/home/xxx/outputs/rms-interface-polish/` and `docs/verification/rms-interface-refinements-2026-11-09.json`.
