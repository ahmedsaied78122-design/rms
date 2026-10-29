# POS Rounding by Restaurant Brand

## Goal

Let a manager choose one whole-Egyptian-pound rounding method per Restaurant Brand. Every branch using that brand inherits the same choice, while another brand may choose a different method. Apply the choice only to future RMS POS invoices; leave ERPNext's global rounding setting and non-POS documents unchanged.

## Approved behavior

- Add a `POS Rounding Method` setting to the existing `Restaurant Brand` form, editable by System Manager.
- Offer `Round Up`, `Nearest`, and `Round Down`. The unit is fixed at EGP 1. Existing brands default to `Nearest`.
- `Round Up` uses ceiling; `Round Down` uses floor; `Nearest` uses conventional commercial rounding, so a half-pound tie goes up. For EGP 80.49, Up gives EGP 81 while Nearest and Down give EGP 80. For EGP 77.50, Nearest gives EGP 78.
- A missing value on an existing or new Restaurant Brand resolves to `Nearest`; a brand without an explicit setting must never fall back to the Frappe-wide Banker's method.
- Round the final payable total after discounts and taxes. Do not change line prices, discount values, tax bases, or the POS Order's calculated source total.
- Keep the unrounded amount in the invoice's `grand_total`; store the payable amount in ERPNext's `rounded_total` and the signed difference in `rounding_adjustment`. Use the Company's normal Round Off Account and cost center.
- The server derives the method from the order's Restaurant Brand. It must not trust a rounding method sent by the browser.
- For a whole-order payment, apply rounding once to the invoice total. For an item-split order, round each guest invoice independently at payment time; the paid progress indicator compares paid rounded invoice totals with the sum of the rounded totals for all guest checks. For an amount split that creates one invoice, round that one invoice once and make its payment shares add up to the rounded amount.
- Amount-split shares keep their existing cents and are balanced to the single rounded invoice total; do not round each share independently. Item-split invoice bases, discounts, and taxes continue to come from the existing assigned-item preview and ERPNext invoice calculation; apply rounding after those calculations.
- The checkout amount, payment validation, change calculation, invoice total display, and receipt must agree on the payable rounded amount for cash, card, and wallet payments.
- If the Company's Round Off Account or cost center is missing, stop before invoice submission and show the existing ERPNext configuration requirement clearly. Do not invent or assign accounting accounts.
- Changing a brand's method affects future payments only; it does not rewrite saved or submitted invoices.

## Scope

### Included

- Brand-level configuration shared across all branches using that brand.
- Backend calculation and validation for standard checkout and both split modes.
- POS payment and invoice values, guest-check progress, and receipt values.
- Focused tests for the three rounding methods, tie behavior, split invoices, mixed payment methods, and unchanged non-POS settings.

### Excluded

- Editing Frappe System Settings or changing rounding for non-POS transactions.
- A per-branch or per-POS-Profile override.
- Configurable rounding increments other than one Egyptian pound.
- Retrofitting prior invoices or changing source order prices, discounts, or tax calculations.

## Risks and controls

- A rounded POS payable differs from the tax-calculated `grand_total`; record the exact difference in ERPNext's standard invoice rounding fields so the ledger remains balanced.
- ERPNext POS Invoice payment and ledger paths use `rounded_total` and `rounding_adjustment`. The implementation must preserve those values through invoice validation and submission, not only set them for display.
- Guest-by-guest rounding can make the combined paid checks differ from the original order's unrounded total; show the rounded amount for each check and reconcile progress against their rounded totals.
- ERPNext requires the Company's Round Off Account and Round Off Cost Center when the adjustment is posted. Use its standard validation/message; do not invent or assign accounting accounts, and ensure an error leaves no partial invoice/payment state.

## Open questions

None. The owner selected POS-only scope, whole-pound increments, per-guest rounding for item-split invoices, and a brand-level shared setting.
