const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const storage = new Map(), alerts = [];
const context = {
 frappe: { pages: { 'point-of-sale': {} }, session: { user: 'cashier@example.com' }, show_alert: value => alerts.push(value) },
 sessionStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
 __: value => value, clearTimeout,
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, 'point_of_sale.js'), 'utf8') + '\nglobalThis.POS = RMSPointOfSale;', context);
function register() {
 const pos = Object.create(context.POS.prototype);
 pos.state = { store: 'STORE-1', session: { name: 'SESSION-1' }, order_name: null, permissions: { can_checkout: true },
  order_types: [{ name: 'صالة', require_table: true }, { name: 'تيك أواي' }, { name: 'توصيل' }], cart: [] };
 pos.page = { main: { find: () => ({ prop() { return this; }, val(value) { pos.selectedType = value; return this; } }) } };
 pos.renderCart = pos.renderFields = pos.updateOrderTypeFields = () => {};
 pos.loadCatalog = async () => { pos.catalogLoads = (pos.catalogLoads || 0) + 1; };
 return pos;
}
async function run() {
 const first = register();
 assert.equal(first.defaultOrderType(), 'تيك أواي');
 first.state.order_name = 'ORDER-9'; first.state.order_type = 'صالة';
 first.rememberCurrentScreen('payment');
 const restored = register();
 restored.pendingResumeContext = restored.readResumeContext();
 const calls = [];
 restored.call = async method => {
  calls.push(method);
  return method === 'get_order_state' ? { status: 'Confirmed' } : { name: 'ORDER-9', store: 'STORE-1', status: 'Confirmed', order_type: 'صالة' };
 };
 restored.loadOrder = async order => {
  restored.state.order_name = order.name; restored.state.order_type = order.order_type;
  restored.rememberCurrentScreen('sale');
 };
 restored.showPaymentScreen = () => { restored.paymentShown = true; restored.rememberCurrentScreen('payment'); };
 await restored.restoreCurrentOrder();
 assert.equal(restored.state.order_name, 'ORDER-9');
 assert.equal(restored.state.order_type, 'صالة', 'resuming an order must keep its saved type');
 assert.ok(restored.paymentShown, 'reload restores the payment screen');
 assert.deepEqual(calls, ['get_order'], 'reload must read the existing order without creating a new one');
 // A new sale clears the saved ID, resets to takeaway and reloads its prices.
 restored.resetSale();
 assert.equal(restored.state.order_name, null);
 assert.equal(restored.state.order_type, 'تيك أواي');
 assert.equal(restored.selectedType, 'تيك أواي');
 assert.equal(restored.catalogLoads, 1);
 assert.equal(restored.readResumeContext(), null);
 // English variants and unavailable takeaway respect the allowed type list.
 restored.state.order_types = [{ name: 'Dine In' }, { name: 'TAKE-AWAY' }];
 assert.equal(restored.defaultOrderType(), 'TAKE-AWAY');
 restored.state.order_types = [{ name: 'Delivery' }];
 assert.equal(restored.defaultOrderType(), 'Delivery');
 // Bootstrap selects takeaway before browsing, but keeps an explicit loaded type.
 const boot = register();
 boot.call = async () => ({ store: { name: 'STORE-1' }, session: { name: 'SESSION-1' },
  brands: [{ name: 'BRAND-1' }], order_types: [{ name: 'صالة' }, { name: 'تيك أواي' }] });
 boot.render = boot.loadContextDetails = boot.applyLaunchContext = () => {};
 boot.showError = error => { throw error; };
 await boot.loadBootstrap('STORE-1');
 assert.equal(boot.state.order_type, 'تيك أواي');
 boot.state.order_type = 'صالة';
 await boot.loadBootstrap('STORE-1');
 assert.equal(boot.state.order_type, 'صالة');
 for (const status of ['Paid', 'Cancelled']) {
  const closed = register();
  closed.pendingResumeContext = { store: 'STORE-1', session: 'SESSION-1', order_name: 'ORDER-9' };
  closed.call = async method => { assert.equal(method, 'get_order'); return { status }; };
  closed.loadOrder = () => { throw new Error('A closed order must not be reopened'); };
  await closed.restoreCurrentOrder();
  assert.equal(closed.state.order_name, null);
 }
 assert.equal(alerts.length, 2);
 const sessionChanged = register();
 sessionChanged.pendingResumeContext = { store: 'STORE-1', session: 'OLD-SESSION', order_name: 'ORDER-9' };
 sessionChanged.call = () => { throw new Error('Do not resume another session'); };
 await sessionChanged.restoreCurrentOrder();
 // Bookmarks belong to the signed-in user, as well as the browser tab.
 first.rememberCurrentScreen('sale');
 context.frappe.session.user = 'another-cashier@example.com';
 assert.equal(register().readResumeContext(), null);
 console.log('PASS: takeaway defaults, new-sale reset, same-order/screen reload, closed-order checks, session and user isolation.');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
