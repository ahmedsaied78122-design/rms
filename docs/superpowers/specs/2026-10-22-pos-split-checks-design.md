# POS Split Checks Design

## Intent
Replace the current payment split UI with guest checks that match how a table actually divides its order. A guest can receive specific full order lines, settle only their own check, and leave other guest checks open for later. Each guest check can be printed on its own.

## User requirements
- Split mode stays explicit: By amount or By items.
- By items assigns complete order lines to one guest each; it does not assign percentages of a line.
- By items is unavailable when fewer than two active order lines exist.
- A guest can pay and print their check while other guests' checks remain unpaid and available.
- After a guest has paid, a cashier can split one selected open guest check again by items only; paid checks and all other open checks remain unchanged.
- Newly added order items are assigned to the first open guest check. Adding items is blocked when every guest check has been paid.
- By amount is unavailable when re-splitting an existing guest check.
- Each guest check can be printed independently before payment; after payment, that guest has an individual POS Invoice receipt.
- Guest cards display side by side on the payment screen, wrapping on narrower screens.
- By amount preserves the existing value allocation behavior and whole-order checkout semantics.

## Proposed behavior
1. Cashier enables Split check and chooses By items.
2. Cashier adds guests and assigns each active order line to exactly one guest. The UI shows each guest's items and calculated total; one order line cannot be divided across guests.
3. Before first payment, the cashier can print any guest's check alone.
4. Pay / Pay and print on a guest check submits only that guest's assigned items as one POS Invoice. Paid guest checks become read-only; unpaid guest checks remain open. The parent order remains active until all checks are paid.
5. Cashier can reload or reopen the order and continue with remaining guest checks. When all guest checks are paid, the parent order becomes Paid and all invoices remain linked for history and reprint.
6. After paying a guest check, the cashier may select any remaining open guest card and split only that card's items among two or more guests. The selected card is replaced by the new open checks; paid checks and other open checks keep their item allocations and totals.
7. If new items are added while at least one guest check remains open, assign them to the first open check and add their net amount to that open balance. Keep the paid check amounts fixed.
8. If an order has only one active line, By items is disabled and the cashier can use By amount or normal checkout. A selected open guest check also needs at least two assigned order lines before it can be split again.

## Data and accounting design
- Add a child table to POS Order for persisted guest checks, with guest label, assigned POS Order Item references, amount, status, and resulting POS Invoice link.
- Add a payment operation scoped to one unpaid guest check. It must lock the POS Order, verify the check still owns its lines, build the invoice from those lines only, and persist the invoice link atomically.
- Keep the source POS Order and kitchen tickets as the preparation record. The split workflow must not resend already confirmed lines or duplicate kitchen tickets.
- The POS Order remains in its existing kitchen status while any guest check remains unpaid. It transitions to Paid only after every guest check has a submitted invoice. Preserve a compatibility link to the final invoice while making all guest invoices discoverable from the order and Sales History.
- Apply order-level discounts and taxes proportionally across the guest checks using ERPNext invoice calculation, and reject a split if invoice rounding would make guest totals inconsistent with the order total.
- Initial item splitting must assign every active order quantity exactly once. Re-splitting a guest check validates against only that check's assigned quantities, then confirms full-order coverage across all paid and open checks.
- Paid guest check totals and allocations are immutable. A re-split replaces only the selected open check; it cannot use amount-based sharing.
- Newly appended items belong to the first open check. Their net value updates that check while paid totals and sibling open-check totals remain fixed.

## Interface
- Replace percentage boxes with clear guest columns/cards: guest name, assigned item list, calculated share, payment method, amount tendered, Print check, Pay, and Pay and print.
- In By items mode, an item selector assigns each full line to exactly one guest; unassigned or multiply assigned lines block payment.
- Each open check with at least two assigned order lines has a Split items action. The dialog contains only that check's items and offers add/remove guest controls without an amount mode.
- After one guest pays, the cashier can add order items and split the selected open check again; its siblings and all paid checks stay unchanged.
- Keep By amount controls separate from item assignment.
- Use a responsive grid: guest cards side by side when there is room and one column on narrow screens.
- Make status visible per guest: Open or Paid, with invoice number for paid checks.

## Constraints and risks
- Existing `POS Order` stores only one `pos_invoice`, marks itself Paid after one invoice, and validates payments against the full order total. Existing `split_order` only splits draft orders. These paths cannot implement partial guest payment safely as-is.
- POS Invoice, stock consumption, payment records, Sales History, and reprints must all agree on which guest lines were invoiced. Existing confirmed kitchen items must remain associated with their original tickets.
- Existing discount approval remains attached to the order's discount and must not be requested or consumed twice as guest checks are paid separately.

## Acceptance checks
- Two lines (e.g. lemonade and tea) assigned to two guests: print lemonade alone, pay and print lemonade, reload order, and see tea still open with only tea on its printout; pay tea and verify both invoices in Sales History.
- Try to pay with an unassigned line or duplicate assignment: payment is blocked before API submission.
- One active line: By items cannot be selected.
- Pay one of three guest checks, re-split a different open check, and verify its paid sibling and other open sibling retain their exact items and totals.
- Add a new item after one guest has paid; verify it appears on the first open card and does not change the paid check total.
- Re-splitting a one-line open check is unavailable; amount-based re-splitting is unavailable.
- Three or more guests: cards lay out side by side and remain usable at mobile width.
- Confirmed orders do not create duplicate kitchen tickets during splitting or partial settlement.
- By amount and normal whole-order payments continue to pass existing regression tests.
