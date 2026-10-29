const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const sourcePath = path.join(__dirname, "point_of_sale.js");
const source = `${fs.readFileSync(sourcePath, "utf8")}\nglobalThis.__RMSPointOfSale = RMSPointOfSale;`;
const backOfficeExpenseSource = fs.readFileSync(path.join(__dirname, "../../../public/js/shift_expense.js"), "utf8");
const styles = fs.readFileSync(path.join(__dirname, "../../../public/css/point_of_sale.css"), "utf8");

async function run() {
	assert.doesNotMatch(source, /data-action="review-expenses"|__\("Review Expenses"\)/, "keep the standalone Review Expenses screen out of the POS toolbar");
	assert.doesNotMatch(source, /get_manager_pending_shift_expenses|issue_shift_expense_approval_code|reject_shift_expense|reviewPendingExpenses/, "keep manager expense review and approval actions out of POS");
	assert.match(source, /set_secondary_action_label\(__\("Authorize Pending Expense"\)\)[\s\S]*?authorizePendingExpense\(context\.pending_expenses\)/, "keep the manager-code entry action for cashiers with pending expenses");
	assert.match(backOfficeExpenseSource, /frm\.add_custom_button\(__\("Issue Approval Code"\)/, "issue manager approval codes from the Shift Expense back-office record");
	assert.match(backOfficeExpenseSource, /frm\.add_custom_button\(__\("Reject Expense"\)/, "keep rejection in the Shift Expense back-office record");
	assert.match(source, /class="rms-payment-panel-head">[\s\S]*?\$\{paymentItemsButton\}/, "place View items beside Payment methods above the discount row");
	assert.doesNotMatch(source, /rms-payment-items-launch-row/, "do not render View items as a separate row");
	assert.match(source, /data-pay-discount-value="percentage"[^>]*step="5"/, "percentage discount slider moves in five point steps");
	assert.match(source, /const max = Number\(this\.activeGuestPayment\?\.grand_total \|\| this\.state\.totals\?\.grand_total \|\| 0\)/, "fixed discount input is capped at the selected check total");
	assert.doesNotMatch(source, /Configured by Back Office for this Store/, "payment UI does not expose the configured discount scope");
	assert.ok(source.includes('const keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "C"]'), "place decimal before zero on the payment keypad");
	assert.match(source, /data-action="payment-open-discount"/, "open discount controls in a dedicated dialog from checkout");
	assert.match(source, /data-action="payment-open-items"/, "open ordinary order item details from checkout");
	assert.match(source, /rms-payment-items-backdrop[\s\S]*rms-payment-items-dialog/, "show order items in a dedicated popup");
	assert.match(styles, /\.rms-payment-items-dialog-body\s*\{[^}]*overflow-y:\s*auto/, "scroll long item lists inside the popup body");
	assert.match(styles, /\.rms-payment-items-dialog\s*\{[^}]*max-height:\s*min\(86vh/, "keep a long items popup within the viewport");
	assert.match(source, /this\.currency\(totals\.tax_total \|\| 0\)/, "show the saved order tax total in the items popup");
	assert.match(styles, /\.rms-payment-panel-head\s*\{[^}]*justify-content:\s*space-between/, "align the order items action with the payment section heading");
	assert.match(source, /const discountTools = canEditDiscount \?/, "keep discount controls available in checkout");
	assert.match(source, /rms-discount-backdrop[\s\S]*rms-discount-dialog/, "render discount controls in a centered overlay dialog");
	assert.match(source, /const title = this\.activeGuestPayment \? __\("Discount for \{0\}"/, "name the guest whose card discount is being edited");
	assert.match(source, /const currentDiscount = this\.activeGuestPayment \? activeGuestCheck\?\.discount_amount/, "show the selected guest card's existing discount in the dialog");
	assert.match(styles, /body \.rms-split-dialog \.rms-guest-checks > \[data-payment-guests\][\s\S]*?grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/, "force two guest cards side by side in the split dialog");
	assert.doesNotMatch(styles, /@media\s*\(max-width:\s*680px\)[\s\S]{0,180}body \.rms-split-dialog \.rms-guest-checks > \[data-payment-guests\][\s\S]{0,100}grid-template-columns:\s*minmax\(0,\s*1fr\)/, "keep split guests side by side at tablet widths");
	assert.match(source, /type === "Percentage" \? __\("Discount %"\) : __\("Discount amount"\)/, "label percentage entry as a percentage and fixed entry as an amount");
	assert.doesNotMatch(source.slice(source.indexOf("renderDiscountApprovalPrompt("), source.indexOf("queuePaymentDiscountPreview(")), /<select data-discount-approver/, "render managers as explicit choices in the approval step");
	assert.match(source, /data-action="payment-discount-approver"/, "select an authorizer before revealing the code step");
	assert.match(source, /if \(action === "payment-discount-approver"\)/, "handle manager selection from approval dialog");
	assert.match(source, /if \(editFields\) editFields\.hidden = true/, "replace discount fields with the manager approval steps");
	assert.match(source, /applyButton\.hidden = true/, "hide Apply while the cashier is choosing a manager");
	assert.match(source, /applyButton\.textContent = __\("Verify and Apply"\); applyButton\.hidden = false/, "show code verification only after a manager is selected");
	assert.match(source, /data-action="payment-discount-close"/, "allow closing the discount dialog");
	assert.ok(source.indexOf('data-mode="items" aria-pressed=') < source.indexOf('data-mode="amount" aria-pressed='), "show item splitting first and equally split second");
	assert.match(source, /this\.paymentSplitMode = activeOrderItemCount >= 2 \? "items" : "amount"/, "default to item split when there are at least two active order lines");
	assert.match(source, /button\.setAttribute\("aria-pressed", String\(button\.dataset\.mode === this\.paymentSplitMode\)\)/, "keep the selected split button synchronized with the active allocation mode");
	assert.match(source, /By items requires at least two active order items/, "prevent item splitting when the order has only one active line");
	assert.match(source, /data-action="guest-check-take-payment"/, "open one separate payment screen for each unpaid guest");
	assert.match(source, /guestPayment[\s\S]*?rms-guest-payment-overview[\s\S]*?renderGuestPaymentProgress\(Number\(this\.state\.totals\?\.grand_total/, "keep the confirmed split and full-order payment progress visible while paying one guest");
	assert.match(source, /renderPaymentGuests\(Boolean\(this\.paymentSplitSetupOpen \|\| this\.activeGuestPayment\)\)/, "show guest cards as a read-only overview during partial payment");
	assert.match(source, /guest\.check_name === this\.activeGuestPayment\?\.guest_check_name/, "identify the guest check being paid now");
	assert.match(source, /class="rms-guest-check-status is-current">\$\{__\("Selected"\)\}/, "label the selected guest check during payment");
	assert.match(source, /const guestResplitButton = activeGuestCheck\?\.status === "Open"[\s\S]*?data-action="guest-check-resplit-current"/, "place re-splitting inside the selected guest's payment screen");
	assert.match(source, /data-split-checks-anchor[\s\S]*?data-guest-checks/, "keep the item split editor available from the partial payment screen");
	assert.match(source, /data-mode="amount">\$\{__\("Equally"\)\}<\/button><\/div><\/div><\/div><p data-split-description hidden><\/p><div data-payment-guests>/, "keep the guest cards outside the toolbar in the partial payment re-split dialog");
	assert.match(source, /activeGuestPayment \? await this.call\("get_guest_check_print_html"/, "print only the active guest check from its payment screen");
	assert.match(source, /data-action="split-item-adjust"/, "move grouped item quantities with simple plus and minus controls");
	assert.match(source, /paymentItemAssignments\[row\.order_item_name\] = allocation/, "store a per-guest quantity for each order line");
	assert.match(source, /paymentItemAssignments\[row\.order_item_name\] = allocation/, "start item allocation at Guest 1 and adjust by quantity");
	assert.match(source, /getPaymentItemGroups\(\)/, "group identical product rows into one visible item row");
	assert.match(source, /allocation = Array\(\(this\.paymentGuests \|\| \[\]\)\.length\)\.fill\(0\); allocation\[0\] = active/, "start all item quantities on Guest 1");
	assert.doesNotMatch(source.slice(source.indexOf("changePaymentGuestCount(delta)"), source.indexOf("async setPaymentSplitMode")), /distributePaymentItemsEvenly/, "adding guests does not redistribute the full order");
	assert.match(source, /handlePaymentKey\(key\)[\s\S]*?this\.paymentKeypadInput = input/, "use the keypad to enter amounts into the selected payment field");
	assert.match(styles, /.rms-guest-checks.is-item-split \.rms-split-description \{ display:none !important; \}/, "remove explanatory copy from the guest card space");
	assert.match(styles, /data-split-balance\]\[data-valid="true"\] \{ display:none !important; \}/, "hide the redundant success status while keeping split errors visible");
	assert.match(styles, /\.rms-payment-layout\.is-item-split > \.rms-payment-keypad \{[\s\S]*?display:block !important;/, "keep the touch keypad available during item split");
	assert.match(styles, /grid-template-columns:repeat\(auto-fit,minmax\(min\(100%,290px\),1fr\)\)/, "keep guest cards side by side when there is room");
	assert.match(styles, /\.rms-split-dialog \.rms-guest-checks > \[data-payment-guests\] \{[^}]*grid-template-columns:repeat\(2,minmax\(0,1fr\)\) !important/, "keep the two split guests side by side in the resplit dialog");
	assert.match(source, /if \(itemSplitActive\)[\s\S]*?this\.paymentInput = guestTender/, "route the touch keypad to visible guest tender fields during item splits");
	assert.match(source, /this\.call\("save_guest_check_allocations"/, "persist guest assignments before printing or payment");
	assert.match(source, /this\.call\("pay_guest_check"/, "submit only the selected guest check for payment");
	assert.ok(source.includes('this.call("pay_guest_check", { order_name: this.state.order_name, guest_check_name: activeGuestPayment.guest_check_name'), "submit multiple payment methods for the selected guest on its own payment screen");
	assert.match(source, /pay_guest_check", \{ order_name: this\.state\.order_name, guest_check_name: activeGuestPayment\.guest_check_name, payments: JSON\.stringify\(payments\), discount_type:/, "submit the selected discount with a guest check payment");
	assert.match(source, /this\.paymentSourceTotal = Number\(this\.paymentDiscountPreview\.grand_total \|\| 0\);[\s\S]*?this\.paymentTotal = this\.roundPosPayable\(this\.paymentSourceTotal\)/, "round the selected guest check's discounted preview total");
	assert.match(source, /guest_check_name: this\.activeGuestPayment\?\.guest_check_name \|\| null/, "preview discounts within the selected guest check");
	assert.match(source, /activeGuestCheck\?\.discount_value/, "reopen the selected guest check with its own discount settings");
	assert.match(source, /renderGuestPaymentProgress\(total\)[\s\S]*?role="progressbar"/, "show cumulative paid progress on the confirmed split");
	assert.match(source, /__\("Paid amount"\)/, "label the cumulative payments with clear wording");
	assert.match(source, /const progress = root\.querySelector\("\[data-guest-payment-progress-container\]"\);[\s\S]*?progress\.innerHTML = this\.renderGuestPaymentProgress\(this\.paymentTotal\)/, "show the paid progress as soon as guest checks are confirmed");
	assert.match(styles, /\.rms-guest-payment-progress-track span \{[^}]*background:#347858/, "fill the payment progress with the RMS identity green");
	assert.match(styles, /\.rms-payment-layout\.is-item-split \.rms-guest-check-actions \{[^}]*grid-template-columns:minmax\(0,1fr\)/, "show just the single Take Payment action on each guest card");
	assert.match(source, /is-guest-check-overview/, "identify the confirmed guest card overview separately from payment screens");
	assert.match(source, /Boolean\(this\.guestSplitFinalized && itemMode && !this\.activeGuestPayment\)/, "hide the keypad based on the confirmed split state rather than the hidden checkbox");
	assert.doesNotMatch(source, /Split confirmed · guest checks are locked|data-split-confirmed-label/, "do not show a locked status label after confirming the split");
	assert.match(styles, /\.rms-payment-layout\.is-guest-check-overview > \.rms-payment-keypad \{ display:none !important; \}/, "hide the keypad only from the confirmed guest overview");
	assert.doesNotMatch(source, /data-item-share|share each item between people/i, "do not split a single line by percentage");
	assert.match(styles, /\.rms-guest-checks\.is-item-split \.[\s\S]*?grid-template-columns:repeat\(auto-fit,minmax\(min\(100%,290px\),1fr\)\)/, "fit split guest cards alongside the touch keypad");
	assert.match(source, /data-action="payment-discount-type"[^>]*aria-pressed=/, "render the selected discount type explicitly");
	assert.match(source, /data-method="OTP" aria-pressed=/, "offer one-time code verification for manager approval");
	assert.match(source, /data-method="Password" aria-pressed=/, "offer the manager's fixed approval password");
	assert.match(source, /approval_method: this\.paymentDiscountAuthMethod/, "tell the API which manager verification method was selected");
	assert.match(source, /preview\.approval_token \|\| approvalCode/, "keep only a server-issued token after fixed-password approval");
	assert.match(styles, /\.rms-discount-auth-switch button\[aria-pressed="true"\][^{]*\{[^}]*#193d3d/, "use the RMS dark green for the selected verification method");
	assert.doesNotMatch(styles.slice(styles.indexOf(".rms-discount-stepper"), styles.indexOf("/* A table map")), /#078ac7|#087fb5|#f2faff/, "remove blue accents from the discount approval flow");
	assert.match(source, /rms-discount-apply[^>]*disabled/, "require a reason before Apply is enabled");
	assert.match(source, /\[data-discount-dialog\] \[data-discount-preview\]/, "keep the preview amount inside the discount dialog");
	assert.match(source, /\.rms-payment-discount-launch \[data-discount-preview\]/, "update the checkout discount summary only after Apply succeeds");
	assert.match(source, /percentageTicks = \[0, 10, 20, 30, 50, 80, 100\]\.map/, "place percentage scale labels at their real slider values");
	assert.match(source, /style="left:\$\{tick\}%"/, "position each percentage label proportionally along the range");
	assert.doesNotMatch(source, /Issue manager code|payment-issue-discount-code/, "remove the obsolete Issue manager code control");
	assert.doesNotMatch(source, /nonCashTender|Change can only be given from a Cash payment|Card and wallet payments exceed/, "accept overpayment on any payment method and show change");
	assert.match(source, /this\.page\.main\.find\("\[data-screen\]"\)\.prop\("hidden", true\);[\s\S]*?this\.page\.main\.find\("\.rms-pos-shell"\)\.prop\("hidden", false\);[\s\S]*?this\.onAction\("new-sale"\);/, "return directly to a clean new order after successful payment");
	assert.doesNotMatch(source, /showPaymentComplete|payment-new-sale|Payment recorded"\)/, "do not show a post-payment confirmation view or toast");
	assert.doesNotMatch(source, /New items confirmed and sent to preparation|frappe\.show_alert\(\{ message: __\("New items confirmed/, "do not show a transient toast after confirming order items");
	const discountInputHandler = source.slice(source.indexOf('root.addEventListener("input"'), source.indexOf('root.addEventListener("focusin"'));
	assert.match(discountInputHandler, /queuePaymentDiscountPreview\(false\)/, "refresh the amount preview while editing without opening manager approval early");
	const roundingHelper = Object.create(contextlessPosPrototype());
	roundingHelper.state = { brand: "BRAND-1", brands: [{ name: "BRAND-1", pos_rounding_method: "Round Up" }] };
	assert.equal(roundingHelper.roundPosPayable(80.49), 81, "Round Up turns 80.49 into 81 based on the selected Restaurant Brand");
	assert.equal(roundingHelper.roundPosPayable(80.49, "Nearest"), 80, "Nearest turns 80.49 into 80");
	assert.equal(roundingHelper.roundPosPayable(80.49, "Round Down"), 80, "Round Down turns 80.49 into 80");
	assert.equal(roundingHelper.roundPosPayable(80.49, "No Rounding"), 80.49, "No Rounding preserves the fractional payable");
	roundingHelper.state.brands[0].pos_rounding_method = "No Rounding";
	assert.equal(roundingHelper.getPosRoundingMethod(), "No Rounding", "honor No Rounding configured on the Restaurant Brand");
	assert.equal(roundingHelper.roundPosPayable(77.50, "Nearest"), 78, "Nearest rounds a half-pound tie up");
	const helpers = Object.create(contextlessPosPrototype());
	let errorToast;
	const errorContext = vm.createContext({ frappe: { pages: { "point-of-sale": {} }, show_alert(config, duration) { errorToast = { config, duration }; } }, __: (value) => value, document: {}, window: {}, Event, setTimeout, clearTimeout });
	vm.runInContext(`${fs.readFileSync(sourcePath, "utf8")}\nglobalThis.__RMSPointOfSale = RMSPointOfSale;`, errorContext);
	Object.create(errorContext.__RMSPointOfSale.prototype).showError({ responseJSON: {
		message: "Internal Server Error", _server_messages: JSON.stringify([JSON.stringify({ message: "Set the Account for Change Amount before accepting overpayment." })]),
		exc: "Traceback (most recent call last): ...",
	} });
	assert.equal(errorToast, undefined, "do not duplicate Frappe's server validation dialog with a POS toast");
	Object.create(errorContext.__RMSPointOfSale.prototype).showError({ message: "The operation could not be completed." });
	assert.equal(errorToast.config.message, "The operation could not be completed.", "show a short toast for client-side errors without server messages");
	assert.equal(errorToast.duration, 7, "keep API errors as short POS alerts");
	assert.deepEqual(Array.from(helpers.getSuggestedPaymentAmounts(155)), [155, 160, 200], "suggest exact, five, ten, and fifty pound rounded amounts without duplicates");
	assert.deepEqual(Array.from(helpers.getSuggestedPaymentAmounts(80)), [80, 100, 200], "offer higher banknote denominations when useful");
	assert.deepEqual(Array.from(helpers.getSuggestedPaymentAmounts(531.07)), [531.07, 535, 540, 550, 600], "suggest the requested rounded amounts for a discounted total of 531.07");
	assert.deepEqual(Array.from(helpers.getSuggestedPaymentAmounts(482.79)), [482.79, 485, 490, 500, 600], "include a 600 pound option for three 200 pound notes");
	let suggestedAmountsHtml = "";
	helpers.paymentTotal = 531.07;
	helpers.currency = (amount) => Number(amount).toFixed(2);
	helpers.page = { main: [{ querySelector(selector) { return selector === "[data-suggested-payment-amounts]" ? { set innerHTML(value) { suggestedAmountsHtml = value; } } : null; } }] };
	helpers.updateSuggestedPaymentAmounts();
	for (const amount of [535, 540, 550, 600]) assert.match(suggestedAmountsHtml, new RegExp(`data-amount="${amount}"`), `render ${amount} after recalculating payment suggestions`);
	const applyDiscountSource = source.slice(source.indexOf("async applyPaymentDiscount()"), source.indexOf("async handleSplitCheckToggle("));
	assert.match(applyDiscountSource, /this\.updateSuggestedPaymentAmounts\(\)/, "recalculate the visible payment suggestions after applying a discount");
	const tenderAmounts = { Cash: 250, "Credit Card": 250, "Mobile Wallet": 250 };
	let remainingText = "";
	let changeText = "";
	let paymentActionsDisabled = false;
	const paymentInputs = Object.entries(tenderAmounts).map(([method, value]) => ({ dataset: { method }, value: String(value), dispatchEvent() { helpers.updatePaymentTotal(); } }));
	helpers.paymentInput = paymentInputs[0];
	helpers.paymentTotal = 250;
	helpers.state = { totals: { grand_total: 250 }, payment_config: [
		{ mode_of_payment: "Cash", type: "Cash" }, { mode_of_payment: "Credit Card", type: "Bank" }, { mode_of_payment: "Mobile Wallet", type: "Wallet" },
	] };
	helpers.currency = (amount) => Number(amount).toFixed(2);
	helpers.page = { main: Object.assign({ find(selector) {
		return { text(value) { if (selector === "[data-payment-remaining]") remainingText = value; if (selector === "[data-change-amount]") changeText = value; return this; }, prop(name, value) { if (selector.includes('data-action="payment-pay"') && name === "disabled") paymentActionsDisabled = value; return this; } };
	} }, { 0: { querySelector: () => null, querySelectorAll: (selector) => selector === "[data-payment-amount]" ? paymentInputs : [] } }) };
	helpers.applySuggestedPaymentAmount(300);
	assert.deepEqual(paymentInputs.map((input) => Number(input.value)), [300, 250, 250], "cash shortcut updates its selected payment method without erasing split allocations");
	assert.equal(changeText, "550.00", "show all tender above the total as change");
	assert.equal(paymentActionsDisabled, false, "do not disable payment for over-tender");
	helpers.paymentTotal = 800;
	helpers.applySuggestedPaymentAmount(300);
	assert.equal(remainingText, "0.00", "cash and non-cash allocations cover the invoice");
	assert.equal(changeText, "0.00", "no change is due when payments match the covered total");
	assert.equal(paymentActionsDisabled, false, "keep payment actions enabled for valid payment allocation");
	helpers.paymentInput = paymentInputs[1];
	helpers.applySuggestedPaymentAmount(700);
	assert.deepEqual(paymentInputs.map((input) => Number(input.value)), [300, 700, 250], "shortcut amount goes into the currently selected card field");
	assert.equal(changeText, "450.00", "calculate change from the combined cash, card, and wallet tender");
	paymentInputs[0].value = "50";
	paymentInputs[1].value = "700";
	paymentInputs[2].value = "0";
	helpers.paymentTotal = 28.5;
	helpers.updatePaymentTotal();
	assert.equal(changeText, "721.50", "show the correct change for the reported 700 plus 50 tender on a 28.50 order");
	let cleared = false;
	const keypadInput = { isConnected: true, value: "25", dispatchEvent(event) { cleared = event.type === "input"; } };
	helpers.paymentInput = keypadInput;
	helpers.handlePaymentKey("C");
	assert.equal(keypadInput.value, "", "C clears the selected tender amount");
	assert.equal(cleared, true, "clearing refreshes remaining and change calculations");
	helpers.handlePaymentKey("4"); helpers.handlePaymentKey("2"); helpers.handlePaymentKey("."); helpers.handlePaymentKey("5");
	assert.equal(keypadInput.value, "42.5", "touch keypad starts a fresh entry after selecting a tender field");
	let dialogConfig;
	let dialog;
	let flowHtml = "";
	let primaryDisabled = true;
	const handlers = {};
	let hideCount = 0;
	const wrapper = {
		addClass() { return this; },
		show() { return this; },
		hide() { hideCount += 1; return this; },
		on(_event, selector, callback) { handlers[selector] = callback; return this; },
		off() { return this; },
		find(selector) {
			if (selector === "[data-option-flow]") return { html(value) { flowHtml = value; } };
			if (selector === ".modal-footer .btn-primary") return { prop(_name, value) { primaryDisabled = value; } };
			return { html() {}, prop() {} };
		},
	};
	const frappe = {
		pages: { "point-of-sale": {} },
		ui: { Dialog: class {
			constructor(config) { dialogConfig = config; this.$wrapper = wrapper; dialog = this; }
			show() {}
			hide() { hideCount += 1; }
			get_value(fieldname) { return fieldname === "quantity" ? 2 : fieldname === "notes" ? "خفيف سكر" : undefined; }
		} },
		msgprint(message) { throw new Error(message); },
	show_alert() {},
	};
	const context = vm.createContext({ frappe, __: (value) => value, document: {}, window: {}, setTimeout, clearTimeout });
	vm.runInContext(source, context, { filename: sourcePath });
	const pos = Object.create(context.__RMSPointOfSale.prototype);
	pos.state = { store: "STORE-1", brand: "BRAND-1", order_type: "Dine In" };
	pos.escape = (value) => String(value);
	pos.currency = (value) => `${value} EGP`;
	pos.showError = (error) => { throw error; };
	const itemDialogUi = Object.create(context.__RMSPointOfSale.prototype);
	itemDialogUi.state = { cart: [
		{ order_item_name: "LEMON-1", item_code: "LEMON", title: "Mint Lemonade", qty: 1, price: 68, uom: "Nos", modifier_labels: [] },
		{ order_item_name: "LEMON-2", item_code: "LEMON", title: "Mint Lemonade", qty: 2, price: 68, uom: "Nos", modifier_labels: [] },
		{ order_item_name: "LEMON-3", item_code: "LEMON", title: "Mint Lemonade", qty: 3, price: 68, uom: "Nos", modifier_labels: [] },
		{ order_item_name: "LEMON-MODIFIED", item_code: "LEMON", title: "Mint Lemonade", qty: 1, price: 68, uom: "Nos", modifier_labels: [{ title: "Extra Mint", price: 3 }] },
		{ order_item_name: "WATER-1", item_code: "WATER", title: "Nile Valley Water 600 ml", qty: 1, price: 25, uom: "Nos", modifier_labels: [] },
	], totals: { subtotal: 506, tax_total: 70.84, grand_total: 576.84 } };
	itemDialogUi.escape = (value) => String(value);
	itemDialogUi.currency = (value) => `${Number(value).toFixed(2)} EGP`;
	const itemDialogHtml = itemDialogUi.renderPaymentItemsDialog();
	assert.equal((itemDialogHtml.match(/class="rms-payment-items-row"/g) || []).length, 3, "group identical order lines while keeping modified items separate");
	assert.match(itemDialogHtml, /Mint Lemonade[\s\S]*?6 Nos × 68\.00 EGP[\s\S]*?<strong>408\.00 EGP<\/strong>/, "show six identical lemonades as one quantity-six row");
	assert.match(itemDialogHtml, /Extra Mint/, "keep modifier details on their distinct item row");
	const splitUi = Object.create(context.__RMSPointOfSale.prototype);
	splitUi.state = { cart: [
		{ order_item_name: "ROW-LEMON", title: "Lemonade", qty: 1, price: 68 },
		{ order_item_name: "ROW-LEMON-2", title: "Lemonade", qty: 1, price: 68 },
		{ order_item_name: "ROW-TEA", title: "Tea", qty: 2, price: 15 },
	] };
	splitUi.paymentSplitMode = "items";
	splitUi.guestCheckState = { guest_checks: [
		{ name: "CHECK-1", guest_name: "Guest One", status: "Open", grand_total: 136, items: [{ name: "ROW-LEMON", qty: 1 }, { name: "ROW-LEMON-2", qty: 1 }] },
		{ name: "CHECK-2", guest_name: "Guest Two", status: "Open", grand_total: 0, items: [] },
		{ name: "CHECK-3", guest_name: "Guest Three", status: "Open", grand_total: 30, items: [{ name: "ROW-TEA", qty: 2 }] },
	] };
	splitUi.paymentGuests = [
		{ name: "Guest One", method: "Cash", amount: 68, due: 68 },
		{ name: "Guest Two", method: "Cash", amount: 0, due: 0 },
		{ name: "Guest Three", method: "Cash", amount: 30, due: 30 },
	];
	splitUi.paymentGuestMethods = [{ mode_of_payment: "Cash" }];
	splitUi.paymentItemAssignments = { "ROW-LEMON": [1, 0, 0], "ROW-LEMON-2": [1, 0, 0], "ROW-TEA": [0, 0, 2] };
	splitUi.guestSplitFinalized = false;
	splitUi.escape = (value) => String(value);
	splitUi.currency = (value) => `${Number(value).toFixed(2)} EGP`;
	const splitSetupHtml = splitUi.renderPaymentGuests(true);
	assert.match(splitSetupHtml, /Tea/, "keep zero-quantity products visible while assigning items");
	assert.doesNotMatch(splitSetupHtml, /data-guest-method|data-guest-amount|data-action="guest-check-pay"/, "keep payment actions out of the setup dialog");
	splitUi.guestSplitFinalized = true;
	const splitGuestHtml = splitUi.renderPaymentGuests();
	const splitDialogHtml = splitUi.renderPaymentSplitDialog();
	assert.match(splitDialogHtml, /data-split-dialog role="dialog"/, "open split setup in an accessible modal");
	assert.match(splitDialogHtml, /data-split-modal-host/, "render split setup inside the modal");
	assert.match(source, /data-mode="items"[\s\S]*data-mode="amount"/, "choose item assignment first and equal sharing second in the modal content");
	assert.match(splitDialogHtml, /data-action="payment-confirm-split"/, "confirm the split before guest checks become available");
	assert.doesNotMatch(splitDialogHtml, /data-action="guest-check-take-payment"/, "do not expose payment actions before confirming the split");
	splitUi.paymentResplitGuestIndex = 0;
	const resplitDialogHtml = splitUi.renderPaymentSplitDialog();
	assert.match(resplitDialogHtml, /Assign this open check's items to guests/, "explain that re-splitting applies only to the selected check");
	assert.doesNotMatch(resplitDialogHtml, /equal shares/, "do not offer amount-based splitting when re-splitting");
	splitUi.paymentResplitGuestIndex = null;
	assert.equal((splitGuestHtml.match(/class="rms-guest-check /g) || []).length, 3, "render a separate side-by-side guest card for each person");
	const guestOneCard = splitGuestHtml.split("<article class=\"rms-guest-check ")[1];
	const guestThreeCard = splitGuestHtml.split("<article class=\"rms-guest-check ")[3];
	assert.match(guestOneCard, /Lemonade/, "show each assigned item inside its guest check");
	assert.equal((guestOneCard.match(/class="rms-guest-item"/g) || []).length, 1, "render only assigned product groups after confirming the split");
	assert.match(styles, /\.rms-guest-item \{ display:grid; grid-template-columns:minmax\(0,1fr\) auto/, "keep the item name full width and place its quantity controls at the row end");
	assert.match(styles, /\.rms-guest-item-copy strong \{[^}]*white-space:normal/, "allow long product names to wrap instead of truncating");
	assert.match(guestOneCard, /Lemonade[\s\S]*?<b>2<\/b>/, "show the grouped quantity for repeated product lines");
	assert.match(guestThreeCard, /Tea/, "support assigning an item to a third guest");
	assert.equal((splitGuestHtml.match(/data-action="guest-check-take-payment"/g) || []).length, 3, "render one Take Payment action for each unpaid guest");
	assert.equal((splitGuestHtml.match(/data-action="guest-check-resplit-current"/g) || []).length, 0, "keep the re-split action off the guest overview cards");
	assert.doesNotMatch(splitGuestHtml, /data-guest-method|data-guest-amount|data-action="guest-check-pay-print"|data-action="guest-check-print"/, "keep payment controls off confirmed guest cards");
	assert.doesNotMatch(guestThreeCard, /Lemonade/, "hide zero-quantity items from finalized guest cards");
	const lockedSplitHtml = splitUi.renderPaymentGuests();
	assert.match(lockedSplitHtml, /data-action="split-item-adjust"[^>]*disabled/, "disable item reassignment after confirming the split");
	assert.match(lockedSplitHtml, /data-guest-name[^>]*disabled/, "lock guest names after confirming the split");
	assert.doesNotMatch(lockedSplitHtml, /data-action="guest-check-resplit-current"/, "keep the re-split action off the guest overview cards");
	assert.match(source, /this\.paymentSplitMode = "items";[\s\S]*this\.paymentResplitGuestIndex/, "re-split mode is item-only and remembers the selected guest card");
	assert.match(source, /this\.call\("resplit_open_guest_check"/, "save the selected guest's item split without editing the other cards");
	const quantityUi = Object.create(context.__RMSPointOfSale.prototype);
	quantityUi.state = { cart: [{ order_item_name: "ROW-CHICKEN", title: "Chicken", qty: 7, price: 100 }, { order_item_name: "ROW-TEA", title: "Tea", qty: 1, price: 20 }] };
	quantityUi.paymentSplitMode = "items";
	quantityUi.paymentGuests = [{ name: "Guest 1" }, { name: "Guest 2" }];
	quantityUi.paymentItemAssignments = { "ROW-CHICKEN": [7, 0], "ROW-TEA": [1, 0] };
	quantityUi.syncPaymentGuestFields = () => {};
	quantityUi.renderPaymentItemAssignments = () => {};
	quantityUi.updateGuestSplitAmounts = () => {};
	const chickenGroup = quantityUi.getPaymentItemGroups().find((group) => group.title === "Chicken");
	quantityUi.adjustPaymentItemAllocation(chickenGroup.key, 1, 1);
	assert.deepEqual(quantityUi.paymentItemAssignments["ROW-CHICKEN"], [6, 1], "plus transfers one unit from Guest 1 even when the order line quantity is seven");
	quantityUi.paymentResplitGuestIndex = 0;
	quantityUi.paymentResplitItemNames = ["ROW-CHICKEN", "ROW-TEA"];
	quantityUi.guestCheckState = { guest_checks: [{ items: [{ name: "ROW-CHICKEN", qty: 6 }, { name: "ROW-TEA", qty: 1 }] }] };
	quantityUi.renderPaymentItemAssignments = () => {};
	quantityUi.updateGuestSplitAmounts = () => {};
	const teaGroup = quantityUi.getPaymentItemGroups().find((group) => group.title === "Tea");
	quantityUi.adjustPaymentItemAllocation(teaGroup.key, 1, 1);
	assert.equal(quantityUi.guestCheckState.guest_checks[0].items.length, 2, "keep the selected guest check's source quantities while recalculating a re-split");
	const root = {
		name: "FRAPPE", title: "Frappé", has_options: true, options: [
			{ name: "FLAVOR-CARAMEL", title: "Caramel", has_options: true, price: null },
		], modifier_groups: [],
	};
	const sizeConfig = {
		name: "FLAVOR-CARAMEL", title: "Caramel", has_options: true, options: [
			{ name: "FRAPPE-CARAMEL-LARGE", title: "Large", has_options: false, price: 120 },
		], modifier_groups: [],
	};
	const finalConfig = {
		name: "FRAPPE-CARAMEL-LARGE", title: "Frappé Caramel - Large", has_options: false, price: 120,
		uom: "Nos", must_be_whole_number: false,
		modifier_groups: [{ name: "MILK", title: "Milk", allow_multiple_selections: false, options: [
			{ name: "WHOLE-MILK", title: "Whole Milk", selling_price: 0 },
		] }],
	};
	pos.call = async (_method, { product }) => product === "FLAVOR-CARAMEL" ? sizeConfig : finalConfig;
	pos.pushCart = (...args) => { pos.added = args; };

	pos.showProductOptions(root, "FRAPPE");
	assert.equal((flowHtml.match(/rms-pos-option-level/g) || []).length, 1, "show the first choice in the single modal");

	await handlers["[data-option-depth]"]({ currentTarget: { dataset: { optionDepth: "0" }, value: "FLAVOR-CARAMEL" } });
	assert.equal((flowHtml.match(/rms-pos-option-level/g) || []).length, 2, "keep the flavor and size choices visible together");
	assert.equal(hideCount, 0, "do not close the modal between option levels");

	await handlers["[data-option-depth]"]({ currentTarget: { dataset: { optionDepth: "1" }, value: "FRAPPE-CARAMEL-LARGE" } });
	assert.match(flowHtml, /Milk/);
	assert.equal(primaryDisabled, false, "enable Add to order once a priced leaf option is selected");
	assert.equal(hideCount, 0, "keep modifiers in the same modal as product options");

	handlers["[data-modifier-key]"]({ currentTarget: {
		dataset: { modifierKey: "MILK:WHOLE-MILK", group: "MILK" }, type: "radio", checked: true,
	} });
	await dialogConfig.primary_action({ quantity: 2, notes: "خفيف سكر" });
	assert.equal(hideCount, 1, "close the modal only after adding the configured product");
	assert.equal(pos.added[0], "FRAPPE-CARAMEL-LARGE");
	assert.equal(pos.added[1], "FRAPPE");
	assert.deepEqual(JSON.parse(JSON.stringify(pos.added[2])), [{ modifier_group: "MILK", modifier_product: "WHOLE-MILK", qty: 1 }]);
	assert.equal(pos.added[4].qty, 2);
	assert.equal(pos.added[4].notes, "خفيف سكر");

	let productHtml = "";
	let productCountText = "";
	pos.page = { main: { find(selector) {
		if (selector === '[data-role="catalog-count"]') return { text(value) { productCountText = value; } };
		if (selector === '[data-role="products"]') return { html(value) { productHtml = value; } };
		throw new Error(`Unexpected selector: ${selector}`);
	} } };
	pos.state = {
		session: { name: "SESSION-1" },
		permissions: { can_checkout: true },
		catalog_mode: "products",
		bootstrap_loading: false,
		catalog_loading: false,
		products: [
			{ name: "UNPRICED-ALMOND-TART", title: "Almond Tart", price: null, has_options: false },
			{ name: "FRESH-MANGO-JUICE", title: "Fresh Mango Juice", price: null, has_options: true },
		],
	};
	pos.renderProducts();
	const unpricedTile = productHtml.match(/<button[^>]*data-product="UNPRICED-ALMOND-TART"[^>]*>/)?.[0];
	const optionParentTile = productHtml.match(/<button[^>]*data-product="FRESH-MANGO-JUICE"[^>]*>/)?.[0];
	assert.ok(unpricedTile?.includes("disabled"), "disable a regular product without a price");
	assert.match(productHtml, /Almond Tart[\s\S]*Price not set/, "explain why the unpriced product cannot be added");
	assert.ok(optionParentTile && !optionParentTile.includes("disabled"), "keep an option parent selectable without its own price");
	assert.match(productHtml, /Choose option/, "tell the cashier to open the parent product options");
	assert.equal(productCountText, "{0} products");
	let discountInput = 10;
	let discountType = "Percentage";
	let paymentTotalText = "";
	let paymentDiscountText = "";
	const pendingPreviews = [];
	const discountFeedback = { textContent: "", innerHTML: "" };
	const discountPreviewLabel = { set textContent(value) { paymentDiscountText = value; } };
	let approvalCodeFocused = false;
	const approvalCodeInput = { focus() { approvalCodeFocused = true; } };
	pos.page = { main: Object.assign({ find(selector) {
		if (selector === "[data-pay-discount-type]") return { val: () => discountType };
		if (selector.startsWith('[data-pay-discount-value=')) return { val: () => discountInput };
		if (selector === "[data-pay-discount-reason]") return { val: () => "" };
		if (selector === "[data-discount-percent-label]") return { text() {} };
		if (selector === ".rms-payment-total") return { text(value) { paymentTotalText = value; } };
		if (selector === "[data-discount-preview]") return { text(value) { paymentDiscountText = value; } };
		throw new Error(`Unexpected selector: ${selector}`);
	} }, { 0: { querySelector: (selector) => selector === "[data-discount-approval-feedback]" ? discountFeedback : selector === "[data-discount-dialog] [data-discount-preview]" ? discountPreviewLabel : selector === "[data-discount-approval-code]" ? approvalCodeInput : null, querySelectorAll: () => [] } }) };
	pos.state = { order_name: "ORDER-1", totals: { grand_total: 100 } };
	pos.currency = (value) => String(value);
	pos.updatePaymentTotal = () => {};
	pos.call = (_method, args) => new Promise((resolve) => pendingPreviews.push({ value: args.discount_value, resolve }));
	pos.discountPreviewRequestId = 1;
	const stalePreview = pos.refreshPaymentDiscountPreview(1, "", false);
	discountInput = 20;
	pos.discountPreviewRequestId = 2;
	const currentPreview = pos.refreshPaymentDiscountPreview(2, "", false);
	assert.equal(pendingPreviews.length, 2);
	pendingPreviews[1].resolve({ grand_total: 80, discount_amount: 20, requires_manager_approval: true,
		approvers: [{ user: "manager@example.com", full_name: "POS Manager" }] });
	await currentPreview;
	pendingPreviews[0].resolve({ grand_total: 90, discount_amount: 10 });
	await stalePreview;
	assert.equal(paymentTotalText, "", "keep a discount preview from changing the payable total before Apply");
	assert.equal(paymentDiscountText, "20", "keep the latest discount amount when an older preview returns late");
	assert.equal(pos.paymentDiscountPreview.requires_manager_approval, true, "retain an over-limit preview without making it payable");
	assert.equal(discountFeedback.innerHTML, "", "do not open the manager step until Apply is pressed");
	pos.discountPreviewRequestId = 3;
	const approvalPreview = pos.refreshPaymentDiscountPreview(3, "", true);
	assert.equal(pendingPreviews.length, 3);
	pendingPreviews[2].resolve({ grand_total: 80, discount_amount: 20, requires_manager_approval: true,
		approvers: [{ user: "manager@example.com", full_name: "POS Manager" }] });
	await approvalPreview;
	assert.equal(pos.paymentDiscountPreview, null, "require manager approval before making an over-limit discount payable");
	assert.match(discountFeedback.innerHTML, /manager@example\.com/, "show an approver after Apply when discount exceeds the cashier limit");
	discountInput = 5;
	pos.discountPreviewRequestId = 4;
	const permittedPreview = pos.refreshPaymentDiscountPreview(4, "", false);
	assert.equal(pendingPreviews.length, 4);
	pendingPreviews[3].resolve({ grand_total: 95, discount_amount: 5, requires_manager_approval: false });
	await permittedPreview;
	assert.equal(discountFeedback.innerHTML, "", "clear a stale manager prompt when the discount is within the cashier limit");
	assert.equal(discountFeedback.textContent, "", "remove stale manager guidance after a permitted discount preview");
	assert.equal(pos.paymentDiscountPreview.grand_total, 95, "retain a permitted preview for the Apply action");
	discountType = "Amount";
	discountInput = 101;
	pos.discountPreviewRequestId = 5;
	await pos.refreshPaymentDiscountPreview(5, "", false);
	assert.equal(paymentDiscountText, "—", "clear the previous calculated discount when the entered amount is invalid");
	assert.equal(pos.paymentDiscountPreview, null, "do not retain a stale valid discount preview for an invalid amount");
	const dialogContext = Object.create(contextlessPosPrototype());
	dialogContext.paymentDiscount = { type: "Percentage", value: 20, reason: "" };
	dialogContext.state = { totals: { grand_total: 100, discount_amount: 20 } };
	dialogContext.escape = (value) => String(value);
	dialogContext.currency = (value) => Number(value || 0).toFixed(2);
	assert.match(dialogContext.renderPaymentDiscountDialog(), /<span>Discount %<\/span>/, "show a percentage label beside the percentage control");
	dialogContext.paymentDiscount.type = "Amount";
	assert.match(dialogContext.renderPaymentDiscountDialog(), /<span>Discount amount<\/span>/, "show an amount label beside the amount control");
	const approvers = [{ user: "manager@example.com", full_name: "POS Manager" }];
	pos.renderDiscountApprovalPrompt(approvers, "");
	assert.match(discountFeedback.innerHTML, /data-action="payment-discount-approver"/, "show manager choices after Apply requires approval");
	assert.doesNotMatch(discountFeedback.innerHTML, /data-discount-approval-code/, "do not ask for a code before manager selection");
	pos.renderDiscountApprovalPrompt(approvers, "manager@example.com");
	assert.match(discountFeedback.innerHTML, /data-discount-approval-code/, "show code input only after selecting a manager");
	assert.match(discountFeedback.innerHTML, /One-time code[\s\S]*Fixed password/, "show both approval methods after selecting a manager");
	pos.renderDiscountApprovalPrompt(approvers, "manager@example.com", "", "", "Password");
	assert.match(discountFeedback.innerHTML, /class="rms-manager-password"[\s\S]*autocomplete="off"/, "render a password field when fixed-password approval is selected");
	assert.match(discountFeedback.innerHTML, /fixed approval password configured on this manager's POS User profile/, "explain where to configure the separate manager password");
	assert.match(discountFeedback.innerHTML, /data-method="Password" aria-pressed="true"/, "visually select fixed-password approval");
	discountFeedback.innerHTML = "";
	pos.paymentDiscountApprovers = approvers;
	pos.selectDiscountApprover("manager@example.com");
	assert.match(discountFeedback.innerHTML, /POS Manager[\s\S]*data-discount-approval-code/, "show the selected manager before revealing the code input");
	assert.equal(approvalCodeFocused, true, "focus the newly revealed code field after manager selection");
	let selectedType = "Percentage";
	const typeButtons = [
		{ dataset: { type: "Amount" }, setAttribute(_name, value) { this.pressed = value; } },
		{ dataset: { type: "Percentage" }, setAttribute(_name, value) { this.pressed = value; } },
	];
	let percentageHidden = false;
	let amountHidden = true;
	const typeHelper = Object.create(contextlessPosPrototype());
	typeHelper.paymentDiscount = { type: "Percentage", value: 15 };
	typeHelper.paymentDiscountDraft = { type: "Percentage", value: 15 };
	typeHelper.page = { main: Object.assign({ find(selector) {
		if (selector === "[data-pay-discount-type]") return { val(value) { if (value !== undefined) selectedType = value; return selectedType; } };
		if (selector === "[data-discount-range-wrap]") return { prop(_name, value) { percentageHidden = value; } };
		if (selector === "[data-discount-amount-wrap]") return { prop(_name, value) { amountHidden = value; } };
		throw new Error(`Unexpected selector: ${selector}`);
	} }, { 0: { querySelectorAll: () => typeButtons } }) };
	typeHelper.clearDiscountApprovalPrompt = () => {};
	typeHelper.setPaymentDiscountType("Amount");
	assert.equal(selectedType, "Amount", "persist the selected discount type in the payment form");
	assert.equal(percentageHidden, true, "hide percentage slider in fixed amount mode");
	assert.equal(amountHidden, false, "show fixed amount input in fixed amount mode");
	assert.equal(typeButtons[0].pressed, "true");
	assert.equal(typeButtons[1].pressed, "false");
	let reasonValue = "";
	let discountValue = "10";
	let applyDisabled = false;
	const applyStateHelper = Object.create(contextlessPosPrototype());
	applyStateHelper.page = { main: { 0: { querySelector(selector) {
		if (selector === "[data-action='payment-apply-discount']") return { hidden: false, set disabled(value) { applyDisabled = value; } };
		if (selector === "[data-pay-discount-type]") return { value: "Amount" };
		if (selector === '[data-pay-discount-value="amount"]') return { value: discountValue };
		if (selector === "[data-discount-approval-code]") return null;
		if (selector === "[data-pay-discount-reason]") return { value: reasonValue };
		return null;
	} } } };
	applyStateHelper.updateDiscountApplyState();
	assert.equal(applyDisabled, true, "keep Apply disabled without a discount reason");
	reasonValue = "Customer recovery";
	applyStateHelper.updateDiscountApplyState();
	assert.equal(applyDisabled, false, "enable Apply after a discount reason is entered");
	frappe.show_alert = () => {};
	let paymentCalls = 0;
	let finishPayment;
	let payButtonsDisabled = false;
	let paymentScreenHidden = false;
	let orderShellHidden = true;
	let nextSaleAction = null;
	const amountInput = { dataset: { method: "Cash" }, value: "10" };
	pos.page = { main: Object.assign({ find(selector) {
		return { prop(name, value) {
			if (selector.includes("payment-pay") && name === "disabled") payButtonsDisabled = value;
			if (selector === "[data-screen]" && name === "hidden") paymentScreenHidden = value;
			if (selector === ".rms-pos-shell" && name === "hidden") orderShellHidden = value;
			return this;
		} };
	} }, { 0: { querySelector: () => null, querySelectorAll: (selector) => selector === "[data-payment-amount]" ? [amountInput] : [] } }) };
	pos.onAction = (action) => { nextSaleAction = action; };
	pos.state = { order_name: "ORDER-1", totals: { grand_total: 10 } };
	pos.paymentTotal = 10;
	pos.paymentDiscount = { type: "Percentage", value: 0, reason: "" };
	pos.paymentSubmitting = false;
	pos.call = () => { paymentCalls += 1; return new Promise((resolve) => { finishPayment = resolve; }); };
	const firstSubmission = pos.submitPayment(false);
	const repeatedSubmission = pos.submitPayment(false);
	assert.equal(paymentCalls, 1, "ignore a second payment action while the first request is pending");
	assert.equal(payButtonsDisabled, true, "disable both payment actions during submission");
	finishPayment({ pos_invoice: "POSINV-1", status: "Paid" });
	await Promise.all([firstSubmission, repeatedSubmission]);
	assert.equal(paymentCalls, 1, "only submit one invoice request for a double click");
	assert.equal(payButtonsDisabled, true, "keep payment actions disabled after successful payment");
	assert.equal(paymentScreenHidden, true, "hide checkout once payment succeeds");
	assert.equal(orderShellHidden, false, "return to the POS order screen after payment");
	assert.equal(nextSaleAction, "new-sale", "automatically reset into a new sale after payment");
	pos.paymentSubmitting = false;
	payButtonsDisabled = false;
	pos.call = async () => { throw new Error("Temporary network failure"); };
	pos.showError = () => {};
	await pos.submitPayment(false);
	assert.equal(pos.paymentSubmitting, false, "release the submission guard after a failed request");
	assert.equal(payButtonsDisabled, false, "re-enable payment actions after a failed request");
}

function contextlessPosPrototype() {
	const context = vm.createContext({ frappe: { pages: { "point-of-sale": {} } }, __: (value) => value, document: {}, window: {}, Event, setTimeout, clearTimeout });
	vm.runInContext(`${fs.readFileSync(path.join(__dirname, "point_of_sale.js"), "utf8")}\nglobalThis.__RMSPointOfSale = RMSPointOfSale;`, context);
	return context.__RMSPointOfSale.prototype;
}

run().catch((error) => { console.error(error); process.exitCode = 1; });

