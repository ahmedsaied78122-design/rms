# Store-only Slave connection — 2026-11-16

The wizard and connection dialog now accept **Store** as their sole business
selection. Store names appear in the Slave Instance and Master Instance forms,
and the Store shows a link and status for its connected peer. No manual Branch
creation, activation or selection is required. Existing live pair identities
were preserved.

Deployed runtime: Arab Streaming 0.2.17 / `dfe19a6`, RMS `2f292e7`, on the cloud
Master and Saied. A generic provider interface in the canonical streaming app
keeps plain ERPNext's Branch UI available when RMS is absent. RMS provisions its
hidden transport scope automatically on Master Store creation, and the Master
resolves the selected Store under the authenticated key user's Store permissions.
The stable existing transport scope, pairing generation, uniqueness, event and
operational guards continue to enforce isolation.

Verification:

- Complete engine suite: 148 passing tests. Focused engine/RMS selection, policy and onboarding suite: 94 passing tests (the suites overlap).
- A native isolated Store insert created and enabled its transport identity automatically. Pairing resolved from the Store, the Store/Slave views agreed, and a second Slave claiming the same Store was rejected. The pairing used Store authorization even after Branch read permission was removed. This checks link authorization; ordinary bootstrap data permissions still apply.
- The native trial was rolled back; original Store, Branch, peer and state counts were preserved.
- JavaScript checks verified a single Store selection in the link dialog and no Branch labels in wizard Store options.
- Real authenticated wire requests from Saied returned two available Stores and resolved both successfully. The existing wizard endpoint also returned two Store choices and Company setup details.
- Chrome on both live sites displayed the linked Store in each peer form, hid the Branch field, displayed the inverse peer link in the Store, and hid manual routing controls. The Slave's link dialog showed only Store. No browser errors occurred.
- Store mappings and live pairing IDs/generations were compared before and after deployment and browser checks: unchanged. No extra peer was linked on the live sites.
- No active Pending/Failed streaming events remained on either site at the final check.

Private browser-session material, screenshots and actual key credentials are
excluded from this report and Git. See [browser results](browser-results.json).
