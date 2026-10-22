# POS Split Checks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let cashiers assign whole order lines to guest checks, print and pay each guest independently, and keep unpaid guest checks open until settled.

**Architecture:** Add persisted guest-check rows to `POS Order`, each containing a guest, assigned POS Order Item references, state, amount, and its POS Invoice. Add APIs to save assignments, print one guest check, and pay one guest check by reusing the existing invoice-building flow with a strict item filter. Keep the parent order and kitchen tickets as the preparation record; mark the order Paid only when all checks have submitted invoices. Preserve the current amount split as whole-order checkout.

**Tech Stack:** Frappe/ERPNext DocTypes and Python APIs; existing RMS Point of Sale JavaScript and CSS; bench tests and Node regression tests.

**Spec:** `docs/superpowers/specs/2026-10-22-pos-split-checks-design.md`

## Global Constraints

- By items assigns each complete active order line to exactly one guest; item shares across guests are not supported.
- By items is unavailable with fewer than two active order lines.
- A guest payment creates an invoice only for that guest's assigned lines; other checks remain unpaid and available after reload.
- Do not duplicate or resend confirmed kitchen tickets when creating, paying, or printing guest checks.
- A parent order becomes Paid only after every guest check is paid.
- By amount retains its existing whole-order settlement behavior.
- After initial confirmation, only an open check can be split again, and that operation uses item assignments only.
- Re-splitting preserves the selected card's neighbors and all paid card amounts; new items attach to the first open check.
- Apply order discounts and taxes consistently across separate guest invoices; cumulative rounding must be verified against ERPNext calculations.

## Review Focus

- Duplicate, missing, cancelled, or newly appended order lines cannot be invoiced twice or silently omitted; test assignment validation and reload.
- Concurrent payment attempts on the same guest check cannot create duplicate POS Invoices; test document locking and retry behavior.
- Fixed discounts and taxes across multiple checks must not exceed or drift from the order-level totals; test percentage and amount discounts with rounding.
- Partial payment/reload must leave the unpaid guest check active and must not change kitchen ticket counts; test both state and ticket linkage.
- Returns, reprints, and Sales History must resolve every invoice created for a single POS Order; test multi-invoice lookup and authorization.

---

### Task 1: Persist guest-check allocations

**Files:**
- Create: `rms/rms/doctype/pos_order_guest_check/pos_order_guest_check.json`
- Create: `rms/rms/doctype/pos_order_guest_check/__init__.py`
- Modify: `rms/rms/doctype/pos_order/pos_order.json`
- Modify: `rms/rms/doctype/pos_order/pos_order.py`
- Test: `rms/rms/doctype/pos_order/test_pos_order_serialization.py`
- Test: `rms/api/test_pos_order_operations.py`

**Interfaces:**
- Produces a `guest_checks` child table on POS Order. Each row has `guest_name`, `status` (`Open` or `Paid`), `grand_total`, `items_json` (JSON array of POS Order Item names), and `pos_invoice`.
- Produces `validate_guest_check_allocations(order_items, guest_checks) -> normalized_checks`, requiring every active order line exactly once and rejecting cancelled/unknown/duplicate rows. Paid check allocations stay immutable. Adding more lines after a guest has paid is blocked so the settled amount cannot drift.

- [x] **Step 1: Add failing tests** for complete item assignment, duplicate/unassigned/cancelled item rejection, and single-line item-mode rejection.
- [x] **Step 2: Run the focused tests** and confirm they fail for missing DocType/validation.
- [x] **Step 3: Add the child DocType and `guest_checks` table field**, preserving existing POS Order fields and statuses.
- [x] **Step 4: Implement allocation validation** in `pos.py`, using active quantities after cancellations.
- [x] **Step 5: Run focused tests** and verify the allocation validator rejects invalid assignments.

### Task 2: Create and settle one guest invoice safely

**Files:**
- Modify: `rms/api/pos.py`
- Modify: `rms/rms/doctype/pos_order/pos_order.py`
- Test: `rms/api/test_pos_order_operations.py`

**Interfaces:**
- Add `save_guest_check_allocations(order_name, guest_checks) -> {guest_checks, status}` for persisting or refreshing unpaid allocations under a POS Order lock.
- Add `get_guest_checks(order_name) -> {guest_checks, can_split_by_items}` for restoring paid/open state after reload.
- Add `pay_guest_check(order_name, guest_check_name, payments) -> {pos_invoice, guest_check_status, order_status, grand_total}`.
- Add `get_guest_check_print_html(order_name, guest_check_name) -> html` for an unpaid check printout.
- Reuse the invoice construction path from `pay_order` with selected item rows, pro-rated order discount, and check-local tax calculation. Never include items already linked to a Paid guest check.

- [ ] **Step 1: Add failing API tests** for guest-only invoice contents, retry idempotency, one guest paid while another stays open, full settlement changing parent status to Paid, newly appended lines after an earlier check is paid, per-check print contents, check restoration after reload, and unchanged kitchen tickets.
- [ ] **Step 2: Run the focused tests** and verify the current single-invoice API cannot satisfy them.
- [ ] **Step 3: Refactor shared invoice construction** so regular checkout and one-check checkout use the same item/detail/tax/stock rules.
- [x] **Step 4: Implement locked guest-check save, payment, and print APIs**, validating the current order and guest allocation before creating/submitting an invoice.
- [ ] **Step 5: Add discount and rounding tests** for Percentage and Amount discounts across two guest invoices; reject or adjust any allocation whose invoice totals do not reconcile within 0.01 currency units.
- [ ] **Step 6: Run the focused POS API tests** and verify duplicate payment requests return the existing invoice.

### Task 3: Build the guest-check payment interface

**Files:**
- Modify: `rms/rms/page/point_of_sale/point_of_sale.js`
- Modify: `rms/public/css/point_of_sale.css`
- Test: `rms/rms/page/point_of_sale/test_point_of_sale_options.js`

**Interfaces:**
- The screen calls the Task 2 APIs and renders each guest-check result with `guest_name`, item list, `grand_total`, status, and invoice number.
- Each unpaid guest has `Print check`, `Pay`, and `Pay and print` actions; paid guest rows are read-only.

- [ ] **Step 1: Add failing UI tests** for whole-line guest assignment, no percentage inputs, hiding/disabling By items when one active order line exists, side-by-side guest cards, separate print/pay actions, and reload restoration.
- [ ] **Step 2: Run the Node tests** and confirm the expected controls and behavior are absent.
- [x] **Step 3: Replace percentage allocation with one-guest-per-line assignment**, show each guest's item list and calculated amount, and require every active line be assigned exactly once.
- [x] **Step 4: Add guest-scoped print/pay actions** and reload guest-check data whenever the order is reopened.
- [x] **Step 5: Style a responsive guest-card grid** that is side by side on wide screens and single column on narrow screens.
- [x] **Step 6: Run Node tests** and verify the normal payment and By amount modes remain unchanged.

### Task 4: Preserve invoice discovery, reprints, and end-to-end behavior

**Files:**
- Modify: `rms/api/pos.py`
- Modify: `rms/rms/page/point_of_sale/point_of_sale.js`
- Modify: `rms/rms/doctype/pos_order/test_pos_order_serialization.py`
- Test: `rms/api/test_pos_order_operations.py`
- Test: `rms/rms/page/point_of_sale/test_point_of_sale_options.js`

- [ ] **Step 1: Add failing tests** that Sales History exposes every invoice for a split order, reprint permission checks remain session/store scoped, and returns can locate the correct guest invoice.
- [x] **Step 2: Extend invoice lookup and reprint flows** to resolve an invoice from its guest-check row while preserving the existing single-invoice path.
- [x] **Step 3: Run POS API and serialization tests** and verify existing kitchen ticket behavior remains covered.
- [x] **Step 4: Run Node UI tests, `node --check`, `bench build --app rms`, clear the local site cache, and verify `/api/method/ping` returns `pong`.
- [ ] **Step 5: Manually review the split screen** with two lines, two guests, one guest paid and printed, reload, then pay and print the remaining guest.

### Task 5: Continue splitting unpaid guest checks

**Files:**
- Modify: `rms/api/pos.py`
- Modify: `rms/rms/doctype/pos_order/pos_order.py`
- Modify: `rms/rms/page/point_of_sale/point_of_sale.js`
- Test: `rms/api/test_pos_order_operations.py`
- Test: `rms/rms/page/point_of_sale/test_point_of_sale_options.js`

**Interfaces:**
- Add `validate_guest_check_resplit(order_items, existing_checks, target_check_name, replacement_checks)` to validate item-only replacements of one open check and preserve global order allocation.
- Add `resplit_open_guest_check(order_name, guest_check_name, guest_checks)` to persist the replacement under an order lock while preserving paid checks and sibling open checks.
- Add `ensure_guest_check_item_append_only(previous, current)` to accept append-only order lines assigned to the first open check.

- [x] Add failing coverage for paid-check protection, selected-check-only replacement, and automatic first-open assignment for new order lines.
- [x] Implement the locked re-split endpoint and expose it only on open cards with at least two assigned order lines.
- [x] Keep the re-split dialog in item mode and scope its item list and balance check to the selected open card.
- [x] Append new lines to the first open check and keep paid check totals unchanged.
- [x] Run API tests, UI tests, JavaScript syntax check, and bench asset build.



