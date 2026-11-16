# Compact shortcuts and banner alternatives — 2026-11-09

Shortcut status/count metadata is now a small inline badge beside the title, with natural line height and wrapping inside the card. Empty native body/footer elements no longer consume grid rows. Smaller screens use fewer columns to keep the title and metadata alongside each other. The native count calculation, filters and route behavior remain unchanged.

Arabic translations now cover the exact installed workspace format strings, including double-space variants such as `{}  To Deliver`. The full template is translated before the native shortcut widget inserts the count. Available, pending, delivery, receiving, assigned, open and billing labels are covered, together with the installed Learn shortcut titles. English remains the native source text. The merged site Arabic translation dictionary was inspected read-only and includes the added templates.

Following the user's clarification, the Arabic welcome now appears at the top center below the navbar, rather than the screen center. The existing tilted R hero mark is retained. Street-art banner alternatives are previews for selection only; the existing live artwork has not been replaced.

Validation used the native shortcut widget's real `set_count` implementation, real jQuery and native/RMS styles in isolated browser fixtures. Arabic/English labels and inline geometry were checked at 320, 768 and 1600px, including zero counts. The existing ten workspace/editor/account checks also passed. No authenticated user, workspace or business data was modified for testing. Evidence: `/home/xxx/outputs/rms-shortcut-polish/`. Studio CSS asset version: `studio-12`.

This note supersedes the earlier canvas note's two-row shortcut layout and centered vertically welcome placement.
