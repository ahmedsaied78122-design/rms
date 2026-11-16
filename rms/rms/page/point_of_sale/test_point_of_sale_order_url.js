const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const storage = new Map(), historyCalls = [], alerts = [];
const location = { href: 'https://rms.arab-erp.com/app/point-of-sale?other=kept#register' };
const context = {
 URL, clearTimeout,
 window: { location, history: { state: { desk: true }, replaceState(state, title, href) {
  historyCalls.push(href); location.href = href;
 } } },
 frappe: { pages: { 'point-of-sale': {} }, session: { user: 'cashier@example.com' }, show_alert: value => alerts.push(value) },
 sessionStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
 __: value => value,
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, 'point_of_sale.js'), 'utf8') + '\nglobalThis.POS = RMSPointOfSale;', context);
function register() {
 const pos = Object.create(context.POS.prototype);
 pos.state = { store: 'STORE-1', session: { name: 'SESSION-1' }, permissions: { can_checkout: true }, order_types: [], cart: [] };
 pos.saveQueue = Promise.resolve();
 pos.page = { main: { find: () => ({ prop() { return this; } }) } };
 pos.render = pos.renderCart = pos.renderFields = () => {};
 pos.loadCatalog = pos.loadContextDetails = async () => {};
 pos.showError = error => { throw error; };
 pos.loadOrder = async order => {
  pos.state.order_name = order.name; pos.state.order_status = order.status;
  pos.currentOrderScreen = 'sale'; pos.watchCurrentOrder();
 };
 pos.showPaymentScreen = () => { pos.paymentShown = true; pos.rememberCurrentScreen('payment'); };
 return pos;
}
async function run() {
 const pos = register();
 pos.state.order_name = 'أوردر /9 & #?';
 pos.watchCurrentOrder();
 let url = new URL(location.href);
 assert.equal(url.searchParams.get('order'), 'أوردر /9 & #?');
 assert.equal(url.searchParams.get('other'), 'kept');
 assert.equal(url.hash, '#register');
 assert.equal(pos.readOrderRoute().order_name, 'أوردر /9 & #?');
 const replacements = historyCalls.length;
 pos.watchCurrentOrder();
 assert.equal(historyCalls.length, replacements, 'unchanged saves must not change browser history');
 pos.rememberCurrentScreen('payment');
 assert.equal(new URL(location.href).searchParams.get('screen'), 'payment');
 pos.rememberCurrentScreen('sale');
 assert.equal(new URL(location.href).searchParams.has('screen'), false);
 pos.resetSale();
 assert.equal(new URL(location.href).searchParams.has('order'), false, 'new sale clears the previous order URL');
 assert.equal(new URL(location.href).searchParams.get('other'), 'kept');

 // An explicit URL must win over a different locally saved order and branch.
 location.href = 'https://rms.arab-erp.com/app/point-of-sale?order=ORDER-9&screen=payment';
 storage.set('rms-pos-launch-context', JSON.stringify({ store: 'OLD-STORE', order_name: 'OLD-ORDER' }));
 const restored = register(), calls = [];
 restored.pendingResumeContext = { store: 'OLD-STORE', session: 'OLD-SESSION', order_name: 'OLD-ORDER' };
 restored.call = async (method, args) => {
  calls.push({ method, args });
  if (method === 'get_order') {
   assert.equal(args.order_name, 'ORDER-9');
   return { name: 'ORDER-9', store: 'STORE-2', status: 'Confirmed' };
  }
  if (method === 'get_order_state') return { status: 'Confirmed' };
  assert.equal(method, 'get_bootstrap'); assert.equal(args.store, 'STORE-2');
  return { store: { name: 'STORE-2' }, brands: [], order_types: [],
   session: { name: 'SESSION-2', status: 'Open' }, permissions: { can_checkout: true } };
 };
 await restored.openOrderRoute(restored.readOrderRoute());
 assert.equal(restored.state.order_name, 'ORDER-9');
 assert.equal(restored.state.store, 'STORE-2');
 assert.ok(restored.paymentShown);
 assert.equal(new URL(location.href).searchParams.get('order'), 'ORDER-9');
 assert.equal(new URL(location.href).searchParams.get('screen'), 'payment');
 assert.equal(storage.has('rms-pos-launch-context'), false);
 assert.ok(calls.every(call => !['save_order', 'confirm_order', 'pay_order'].includes(call.method)), 'opening a link must only read the order');

 // A fresh tab needs no local bookmark to load the link.
 storage.clear();
 const fresh = register(); fresh.call = restored.call;
 await fresh.openOrderRoute(fresh.readOrderRoute());
 assert.equal(fresh.state.order_name, 'ORDER-9');
 assert.ok(fresh.paymentShown);

 // Query-only Desk navigation is also handled when the Page is already mounted.
 location.href = 'https://rms.arab-erp.com/app/point-of-sale?order=ORDER-10';
 let navigated;
 fresh.openOrderRoute = async route => { navigated = route.order_name; };
 await fresh.consumeLaunchContext();
 assert.equal(navigated, 'ORDER-10');
 location.href = 'https://rms.arab-erp.com/app/point-of-sale';
 context.frappe.route_options = { order: 'ORDER-11', screen: 'payment' };
 assert.equal(fresh.readOrderRoute().order_name, 'ORDER-11', 'support query options delivered by Frappe links');
 fresh.syncOrderRoute();
 assert.equal(context.frappe.route_options.order, undefined);

 // Permission/network failures must not fall back to a different saved order.
 location.href = 'https://rms.arab-erp.com/app/point-of-sale?order=DENIED';
 const denied = register(); let displayedError;
 denied.call = async () => { throw new Error('Permission denied'); };
 denied.showError = error => { displayedError = error.message; };
 await denied.openOrderRoute(denied.readOrderRoute());
 assert.equal(displayedError, 'Permission denied');
 assert.equal(denied.state.order_name, undefined);
 assert.equal(new URL(location.href).searchParams.get('order'), 'DENIED');

 // A link to a closed order clears the bookmark instead of retaining an old order.
 location.href = 'https://rms.arab-erp.com/app/point-of-sale?order=CLOSED';
 const closed = register(); closed.state.order_name = 'OLD-ORDER';
 closed.call = async method => {
  if (method === 'get_order') return { name: 'CLOSED', store: 'STORE-1', status: 'Paid' };
  if (method === 'get_order_state') return { status: 'Paid', is_closed: true };
  return { store: { name: 'STORE-1' }, brands: [], order_types: [], session: { name: 'SESSION-1' } };
 };
 closed.loadOrder = () => { throw new Error('Do not reopen a paid order'); };
 await closed.openOrderRoute(closed.readOrderRoute());
 assert.equal(closed.state.order_name, null);
 assert.equal(new URL(location.href).searchParams.has('order'), false);
 assert.equal(alerts.length, 1);

 // Background order sync must never rewrite the address of another Desk Page.
 location.href = 'https://rms.arab-erp.com/app/customer';
 restored.rememberCurrentScreen('payment');
 assert.equal(location.href, 'https://rms.arab-erp.com/app/customer');
 assert.equal(restored.readOrderRoute(), null);
 console.log('PASS: encoded order URLs, payment links, new-sale cleanup, direct-link precedence, fresh tabs, Desk navigation and permission failures.');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
