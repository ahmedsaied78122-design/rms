# POS branch selector regression — 2026-11-16

Deployed Arab Streaming 0.2.16 (`cd26a28`) and RMS runtime `074d760` to the cloud
Master and Saied. The same versions/commits run on both sites.

The denied-branch dialog was emitted during successful Store filtering:
frappe.throw queued server messages even though its PermissionError was caught.
Master startup also preferred an old active cashier session whose Store is now
Slave-operated, leaving the selector empty or attached to the excluded branch.

The engine now exposes a non-throwing ownership query while retaining its
operational assertion. POS/Kitchen selectors use that query and existing user
assignments. Startup ignores foreign sessions, and an opt-in navigation fallback
clears stale browser order context before loading an allowed Store. Operational
context and ordinary explicit denied bootstrap calls still return 403. A denied
order URL also leaves the allowed Store selector usable.

Local till checks, expenses and returns resolve sessions from locally operated
Stores. A Slave's replicated or historical session and its Opening Entry do not
block or become attached to a new Master local session. Two local active sessions
remain forbidden. Existing sessions/orders/accounting records were preserved.

Observed verification:

- 155 focused Python tests passed, including the engine ownership matrix, message-free selectors, user assignment restrictions, fallback, local session filtering, POS operations and cashier validation.
- 59 related expense, return, closing, approval and order-sync tests passed.
- JavaScript startup, saved order/payment URLs, stale-branch recovery, Desk cache/saved-cart and language regression checks passed.
- A native Master session opened in an unpaired Store using a separate Opening Entry while the original foreign session remained unchanged. A second local session was rejected by both API and controller. The entire trial was rolled back; document/event counts were unchanged.
- Headless Chrome loaded both real sites as Administrator with a stale foreign Store/order bookmark. Master offered NASR and TAGAMOA; both selections worked. Slave offered MAADI only. Both displayed 62 catalog products, had no visible error modal, no POS server messages and no browser exceptions. Temporary browser sessions were used without changing credentials.
- The Page cache marker was advanced to v83 and the Desk script to desk-a-101 so refreshed clients discard cached Page code while preserving saved sale records.

See [browser results](browser-results.json) and [HTTP results](http-results.json).
Screenshots and private test-session material were kept outside Git. No posted
financial or stock records were created by this fix's verification.
