const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const context = {
	frappe: { pages: { "point-of-sale": {} }, show_alert() {}, confirm(message, yes) { context.transfer = yes; } },
	__: value => value, clearTimeout, setTimeout,
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, "point_of_sale.js"), "utf8") +
	"\nglobalThis.POS = RMSPointOfSale;", context);

function createPOS() {
	const pos = Object.create(context.POS.prototype);
	pos.state = { order_name: "ORDER-4", order_status: "Open", session: { name: "SESSION-1" },
		store: "Maadi", brand: "Bayt Al Sharq", order_type: "Takeaway", cart: [{ selling_product: "Rice" }] };
	pos.saveQueue = Promise.resolve();
	pos.page = { main: { find() { return { prop() {} }; } } };
	pos.renderCart = pos.renderFields = pos.showOpenOrders = () => {};
	pos.showError = error => { throw error; };
	pos.orderPayload = () => ({ name: pos.state.order_name });
	return pos;
}

async function run() {
	// Two independent registers share the same server order state.
	let serverStatus = "Open";
	const firstRegister = createPOS();
	const secondRegister = createPOS();
	for (const register of [firstRegister, secondRegister]) {
		register.state.cart[0].saved_to_order = true;
		register.call = async method => {
			assert.equal(method, "get_order_state", "a closed order must be detected before any mutation request");
			return { name: "ORDER-4", status: serverStatus, is_closed: ["Paid", "Cancelled"].includes(serverStatus) };
		};
	}
	assert.equal(await secondRegister.ensureCurrentOrderActive(), true);
	serverStatus = "Cancelled";
	await secondRegister.onAction("quantity", { index: "0", delta: "1" });
	assert.equal(secondRegister.state.order_name, null);
	assert.equal(secondRegister.state.cart.length, 0);
	assert.equal(firstRegister.state.order_name, "ORDER-4", "other registers update when they next act");
	await firstRegister.addProduct("Rice");
	assert.equal(firstRegister.state.order_name, null);

	for (const status of ["Cancelled", "Paid"]) {
		for (const action of ["remove", "notes", "checkout", "customer", "discount", "payment-pay", "open-orders", "table-map"]) {
			const register = createPOS();
			register.state.cart[0].saved_to_order = true;
			register.call = async method => {
				assert.equal(method, "get_order_state", `${action} must stop before processing a ${status} order`);
				return { name: "ORDER-4", status, is_closed: true };
			};
			await register.onAction(action, { index: "0" });
			assert.equal(register.state.order_name, null);
			assert.equal(register.state.store, "Maadi");
		}
	}

	const concurrent = createPOS();
	let completeCheck;
	let stateRequests = 0;
	let recoveries = 0;
	concurrent.call = () => { stateRequests++; return new Promise(resolve => { completeCheck = resolve; }); };
	const recover = concurrent.recoverClosedOrder.bind(concurrent);
	concurrent.recoverClosedOrder = order => { recoveries++; recover(order); };
	const checks = [concurrent.ensureCurrentOrderActive(), concurrent.ensureCurrentOrderActive()];
	assert.equal(stateRequests, 1, "simultaneous actions share a pending state check");
	completeCheck({ name: "ORDER-4", status: "Cancelled", is_closed: true });
	assert.deepEqual(await Promise.all(checks), [false, false]);
	assert.equal(recoveries, 1, "only show one closure notice and one new sale");

	const cancelled = createPOS();
	const calls = [];
	cancelled.call = async method => { calls.push(method); return { status: method === "get_order_state" ? "Open" : "Cancelled" }; };
	cancelled.saveTimer = setTimeout(() => { throw new Error("cancelled draft timer fired"); }, 50);
	await cancelled.onAction("cancel-pos-order", { order: "ORDER-4" });
	assert.equal(cancelled.state.order_status, null);
	assert.equal(cancelled.state.order_name, null);
	assert.equal(cancelled.state.cart.length, 0);
	assert.equal(cancelled.state.store, "Maadi");
	assert.equal(cancelled.state.brand, "Bayt Al Sharq");
	assert.equal(cancelled.state.order_type, "Takeaway");
	assert.equal(cancelled.saveTimer, null);
	assert.equal(await cancelled.persistDraft(), null);
	assert.deepEqual(calls, ["get_order_state", "cancel_order"], "cancelled order must not be sent to save_order again");

	const external = createPOS();
	external.state.cart = [{ selling_product: "Old saved item", saved_to_order: true },
		{ selling_product: "Rice", saved_to_order: false, qty: 2, notes: "No salt", modifiers: [{ modifier_product: "Sauce" }] }];
	const originalError = new Error("Only active unpaid orders can be edited.");
	external.call = async method => {
		if (method === "save_order") throw originalError;
		assert.equal(method, "get_order_state");
		return { name: "ORDER-4", status: "Cancelled", grand_total: 230 };
	};
	let transferredSave = false;
	external.saveDraft = () => { transferredSave = true; };
	assert.equal(await external.persistDraft(), null);
	assert.equal(external.state.order_name, null, "external cancellation must leave the cancelled order");
	assert.equal(external.state.cart.length, 0, "new sale starts empty before transfer is accepted");
	assert.equal(typeof context.transfer, "function");
	context.transfer();
	assert.equal(external.state.cart.length, 1, "only transfer unsaved additions, not previously saved items");
	assert.equal(external.state.cart[0].selling_product, "Rice");
	assert.equal(external.state.cart[0].qty, 2);
	assert.equal(external.state.cart[0].notes, "No salt");
	assert.equal(external.state.cart[0].modifiers[0].modifier_product, "Sauce");
	assert.equal(transferredSave, true);

	const decline = createPOS();
	decline.recoverClosedOrder({ status: "Cancelled" });
	assert.equal(decline.state.order_name, null);
	assert.equal(decline.state.cart.length, 0, "declining transfer leaves the new sale empty");
	const staleTransfer = context.transfer;
	decline.resetSale();
	staleTransfer();
	assert.equal(decline.state.cart.length, 0, "an old transfer prompt cannot affect a later sale");

	const queued = createPOS();
	let releaseQueue;
	queued.saveQueue = new Promise(resolve => { releaseQueue = resolve; });
	queued.call = () => { throw new Error("stale queued save must not reach the server"); };
	const pending = queued.persistDraft();
	queued.resetSale();
	releaseQueue();
	assert.equal(await pending, null);

	const confirming = createPOS();
	confirming.state.order_status = "Confirmed";
	confirming.state.order_types = [];
	confirming.call = async method => {
		if (method === "save_order") throw originalError;
		assert.equal(method, "get_order_state", "checkout must not confirm a cancelled order or the new empty sale");
		return { status: "Cancelled" };
	};
	await confirming.checkout();
	assert.equal(confirming.state.order_name, null);

	const other = createPOS();
	other.call = async method => ({ status: method === "get_order_state" ? "Open" : "Cancelled" });
	await other.onAction("cancel-pos-order", { order: "OTHER-ORDER" });
	assert.equal(other.state.order_name, "ORDER-4", "cancelling another order must not discard the current cart");
	assert.equal(other.state.cart.length, 1);

	// A late response for the previous order must finish before a new sale resets its state.
	const next = createPOS();
	let finishSave;
	next.saveQueue = new Promise(resolve => { finishSave = resolve; }).then(() => {
		next.state.order_name = "ORDER-4";
	});
	const transition = next.onAction("new-sale");
	await Promise.resolve();
	assert.equal(next.state.order_name, "ORDER-4");
	finishSave();
	await transition;
	assert.equal(next.state.order_name, null);
	assert.equal(next.state.order_status, null);
	assert.equal(next.state.cart.length, 0);
	console.log("PASS: cancellation opens a new sale; only unsaved additions transfer with consent; stale saves and prompts cannot affect a later sale.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
