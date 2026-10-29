# POS Brand Rounding Implementation Plan

**Goal:** Add a Restaurant Brand setting for whole-EGP Round Up / Nearest / Round Down, and make checkout, split checks, POS invoices, payments, and receipts use the same payable amount without changing Frappe's global setting.

**Design:** `docs/superpowers/specs/2026-10-27-pos-brand-rounding-design.md`

**Execution approach:** Native implementation in this session. Frontend and backend must share the same rule, and invoice rounding behavior is tied to POS payment validation and general-ledger posting.

## Files and responsibilities

- `rms/rms/doctype/restaurant_brand/restaurant_brand.json` — add a System Manager controlled selector with default `Nearest`.
- `rms/pos_rounding.py` (new) — decimal-safe rounding calculation and invoice adjustment helper; no dependency on browser values.
- `rms/api/pos.py` — expose the brand's method to the UI and use the server-derived method for payable validation and invoice creation.
- `rms/pos_rounding.py` — decimal-safe rounding helper plus a POS Invoice class-extension mixin that reapplies the selected amount after ERPNext calculates taxes and totals.
- `rms/hooks.py` — register `extend_doctype_class` for POS Invoice; keep the existing streaming `doc_events` untouched.
- `rms/rms/page/point_of_sale/point_of_sale.js` — show the same payable total in checkout, discount preview, payment allocation, guest checks, suggested amounts, and paid progress.
- `rms/rms/page/point_of_sale/test_point_of_sale_options.js` — verify the frontend rounding modes and split-total behavior.
- `rms/test_pos_rounding.py` (new) and/or focused cases in `rms/api/test_pos_order_operations.py` — verify backend rounding, invoice fields, and payment validation.
- `rms/public/css/point_of_sale.css` and `rms/hooks.py` — update cache version only if the final layout requires CSS changes.

## Tasks

## Shared interfaces

- Task 1 exposes the Restaurant Brand field `pos_rounding_method` and Python helper `round_pos_payable(amount, method)`; Task 2 receives the same selector through `get_brands`, and Task 3 independently loads that saved field on the server.
- Task 2 uses the same method values and examples as Task 1: 80.49 → 81 / 80 / 80 for Up / Nearest / Down. Task 3 uses the Python helper as payment authority.
- Task 2 and Task 3 agree on guest totals after the POS Order's discount/tax preview; Task 3 remains authoritative when it constructs each POS Invoice.
- Task 3's invoice class extension applies rounding inside `calculate_taxes_and_totals`, before ERPNext validates POS payments, change, outstanding, and status.

### 1. Add brand configuration and a decimal-safe rounding helper

1. Add `pos_rounding_method` to Restaurant Brand with `Round Up`, `Nearest`, and `Round Down`; set both new-record default and blank-value fallback to `Nearest`.
2. Implement a helper that rounds payable totals to one-EGP increments using ceiling, commercial half-up, or floor respectively. Keep original amount precision until this final step.
3. Return the selected method with the authorized brand choices from `get_brands`.
4. Add focused tests proving 80.49 rounds to 81 for Round Up and 80 for Nearest/Round Down; also cover 77.50 ties, exact integers, and zero.
5. Run the focused Python rounding tests.

### 2. Use the brand method throughout the payment UI

1. Add a frontend helper with the same three modes and fallback.
2. Apply it to the whole-order due and every finalized item-split guest check. Keep amount-split shares unrounded individually; they must sum to the single rounded invoice due.
3. Refresh payment inputs and suggested amounts after discount preview using the rounded due. Display rounded payable amounts in finalized guest cards and base paid progress on rounded guest totals/invoice rounded totals.
4. Add JavaScript assertions for all modes, half-pound ties, discount preview updates, and amount-split versus item-split behavior.
5. Run the focused Point of Sale JavaScript checks.

### 3. Make backend validation and POS Invoice posting authoritative

1. Read the rounding method from the order's Restaurant Brand; never accept a method sent by the browser as authority.
2. Keep `expected_grand_total` as the tax-and-discount calculated amount. Compute a separate rounded payable and use it for payment sum validation, overpayment/change, and zero-total decisions.
3. Set the invoice flag before insert/submit so a POS Invoice `validate` hook can restore the brand-rounded value after ERPNext recalculates totals. Preserve standard `rounded_total`, `rounding_adjustment`, base-currency rounding fields, change, outstanding, and status across both validation passes.
4. Compare ERPNext's invoice `grand_total` with the unrounded expected total. For whole-order and amount-split checkout round one invoice once; for item-split checkout round each guest invoice independently after its assigned items, discounts, and taxes are calculated.
5. Verify invoice print/receipt output uses `rounded_total`; update the custom RMS receipt only if it currently displays the raw `grand_total`.
6. Keep ERPNext's Company Round Off Account and Round Off Cost Center validation; do not invent accounting configuration. Confirm failures roll back without leaving a partial invoice/order payment state.
7. Add focused backend cases for Up/Nearest/Down POS invoices, cash change and non-cash exact payment, item-split guest invoices, amount-split one-invoice behavior, discount recalculation, and untouched non-POS invoices/returns.
8. Run the focused RMS backend tests.

### 4. Migrate and verify the local POS flow

1. Run the narrow schema migration needed for the new Restaurant Brand field and clear only the POS cache/assets needed for the current local bench.
2. Open Restaurant Brand and confirm the selector is visible with `Nearest` as the default; open a disposable/open POS order and confirm checkout uses the rounded brand due.
3. Verify Up/Nearest/Down through backend test invoices without paying or submitting an existing business order in the live browser.
4. Confirm non-POS Frappe rounding remains unchanged and review `git diff` to preserve existing POS work.

## Review focus

- ERPNext's own validation may recalculate rounded total and change; assert the brand method survives both insert and submit validation.
- For an item split, display and progress must use each invoice's rounded amount, while the order's source total and taxes remain unrounded.
- For an amount split, do not round each guest share; only the one invoice payable is rounded.
- If round-off account or cost center is absent, ERPNext must reject before the transaction commits; RMS must not create a substitute account.
- Ensure the method sent in the browser cannot override the order brand's saved setting.
