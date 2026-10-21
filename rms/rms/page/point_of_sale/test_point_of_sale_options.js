const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const sourcePath = path.join(__dirname, "point_of_sale.js");
const source = `${fs.readFileSync(sourcePath, "utf8")}\nglobalThis.__RMSPointOfSale = RMSPointOfSale;`;
const styles = fs.readFileSync(path.join(__dirname, "../../../public/css/point_of_sale.css"), "utf8");

async function run() {
	assert.match(source, /data-pay-discount-value="percentage"[^>]*step="5"/, "percentage discount slider moves in five point steps");
	assert.match(source, /const max = Number\(this\.state\.totals\?\.grand_total \|\| 0\)/, "fixed discount input uses the invoice total as its maximum");
	assert.doesNotMatch(source, /Configured by Back Office for this Store/, "payment UI does not expose the configured discount scope");
	assert.ok(source.includes('const keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "C"]'), "place decimal before zero on the payment keypad");
	assert.match(source, /data-action="payment-open-discount"/, "open discount controls in a dedicated dialog from checkout");
	assert.match(source, /rms-discount-backdrop[\s\S]*rms-discount-dialog/, "render discount controls in a centered overlay dialog");
	assert.doesNotMatch(source.slice(source.indexOf("renderDiscountApprovalPrompt("), source.indexOf("queuePaymentDiscountPreview(")), /<select data-discount-approver/, "render managers as explicit choices in the approval step");
	assert.match(source, /data-action="payment-discount-approver"/, "select an authorizer before revealing the code step");
	assert.match(source, /if \(action === "payment-discount-approver"\)/, "handle manager selection from approval dialog");
	assert.match(source, /if \(editFields\) editFields\.hidden = true/, "replace discount fields with the manager approval steps");
	assert.match(source, /applyButton\.hidden = true/, "hide Apply while the cashier is choosing a manager");
	assert.match(source, /applyButton\.textContent = __\("Verify and Apply"\); applyButton\.hidden = false/, "show code verification only after a manager is selected");
	assert.match(source, /data-action="payment-discount-close"/, "allow closing the discount dialog");
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
	assert.deepEqual(Array.from(helpers.getSuggestedPaymentAmounts(155)), [155, 160, 170, 200], "suggest cash amounts rounded to useful EGP denominations");
	assert.deepEqual(Array.from(helpers.getSuggestedPaymentAmounts(80)), [80, 90, 100], "remove duplicate denomination suggestions");
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
	const keypadInput = { value: "25", dispatchEvent(event) { cleared = event.type === "input"; } };
	helpers.paymentInput = keypadInput;
	helpers.handlePaymentKey("C");
	assert.equal(keypadInput.value, "", "C clears the selected tender amount");
	assert.equal(cleared, true, "clearing refreshes remaining and change calculations");
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
	let paymentTotalText = "";
	let paymentDiscountText = "";
	const pendingPreviews = [];
	const discountFeedback = { textContent: "", innerHTML: "" };
	const discountPreviewLabel = { set textContent(value) { paymentDiscountText = value; } };
	let approvalCodeFocused = false;
	const approvalCodeInput = { focus() { approvalCodeFocused = true; } };
	pos.page = { main: Object.assign({ find(selector) {
		if (selector === "[data-pay-discount-type]") return { val: () => "Percentage" };
		if (selector === '[data-pay-discount-value="percentage"]') return { val: () => discountInput };
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
	let applyDisabled = false;
	const applyStateHelper = Object.create(contextlessPosPrototype());
	applyStateHelper.page = { main: { 0: { querySelector(selector) {
		if (selector === "[data-action='payment-apply-discount']") return { hidden: false, set disabled(value) { applyDisabled = value; } };
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

