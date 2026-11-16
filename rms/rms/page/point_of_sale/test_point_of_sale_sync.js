const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const alerts = [], events = {}, subscriptions = [], listeners = {};
let poll;
const context = {
 frappe: { pages: {'point-of-sale': {}}, show_alert(value) { alerts.push(value); }, realtime: {
  socket: {}, on(name, handler) { events[name] = handler; }, off(name) { delete events[name]; },
  doc_subscribe(type, name) { subscriptions.push(name); }, doc_unsubscribe() {}, emit() {},
 } }, __: text => text, console, setTimeout, clearTimeout,
 document: {visibilityState: 'visible', body: {classList: {contains: () => true}}},
 window: {setInterval(handler, ms) { assert.equal(ms, 3000); poll = handler; return 1; }, clearInterval() {},
  addEventListener(name, handler) { listeners[name] = handler; }, removeEventListener(name) { delete listeners[name]; }},
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, 'point_of_sale.js'), 'utf8') + '\nglobalThis.POS = RMSPointOfSale;', context);
function item(name, qty = 1) {return {name, selling_product: name, qty, selling_price: 65, modifiers: [], notes: ''};}
function order(modified, items = [item('Rice')]) {return {name:'ORDER-1', modified, status:'Open', restaurant_brand:'Brand', order_type:'Takeaway', items, grand_total:65 * items.length};}
function create(snapshot = order('v1')) {
 const pos = Object.create(context.POS.prototype);
 pos.state = {order_name:snapshot.name, order_status:snapshot.status, cart:[], store:'Maadi', ...pos.orderMetadata(snapshot)};
 pos.page = {main:{find() {return {prop() {}};}}};
 pos.renderCart = pos.renderFields = () => {};
 pos.refreshPosPermissions = async () => {};
 pos.saveDraft = () => {pos.pendingSaves = (pos.pendingSaves || 0) + 1;};
 pos.showError = error => {throw error;};
 pos.state.cart = pos.mapOrderItems(snapshot);pos.rememberOrderSnapshot(snapshot);
 return pos;
}
async function run() {
 const pos = create();
 pos.state.category = 'Grills';pos.state.search = 'kebab';
 pos.state.cart.push({local_id:'UNSAVED', selling_product:'Pasta', qty:2, notes:'No salt', modifiers:[{modifier_product:'Cheese'}], saved_to_order:false});
 const updated = order('v2', [item('Rice'),item('Remote kebab')]);
 pos.call = async method => method === 'get_order_state' ? {name:'ORDER-1', status:'Open', modified:'v2'} : updated;
 await pos.syncCurrentOrder();
 assert.deepEqual(Array.from(pos.state.cart, row => row.selling_product), ['Rice','Remote kebab','Pasta']);
 assert.equal(pos.state.cart[2].qty,2);assert.equal(pos.state.cart[2].notes,'No salt');
 assert.equal(pos.state.cart[2].modifiers[0].modifier_product,'Cheese');
 assert.equal(pos.state.category,'Grills');assert.equal(pos.state.search,'kebab');
 await pos.syncCurrentOrder();assert.equal(pos.state.cart.length,3,'repeated notifications must not duplicate additions');

 const dirty = create();dirty.state.cart[0].qty = 2;
 dirty.applyOrderSnapshot(updated);
 assert.equal(dirty.state.cart[0].qty,2,'keep local changes when the other page only changed a different row');
 assert.equal(dirty.pendingSaves,1);
 const conflict = create();conflict.state.cart[0].qty = 2;
 conflict.applyOrderSnapshot(order('v3',[item('Rice',3)]));
 assert.equal(conflict.state.cart[0].qty,3,'same-row conflict must not overwrite the other page');
 assert(alerts.some(value=>value.message.includes('latest saved changes')));
 const removed = create();removed.state.cart = [];
 removed.applyOrderSnapshot(updated);
 assert.deepEqual(Array.from(removed.state.cart,row=>row.selling_product),['Remote kebab'],'preserve local removal without deleting a remote addition');

 const old = create();let reply;
 old.call = () => new Promise(resolve=>{reply=resolve;});
 const syncing = old.syncCurrentOrder();old.resetSale();
 reply({name:'ORDER-1',status:'Open',modified:'v2'});await syncing;
 assert.equal(old.state.order_name,null);assert.equal(old.state.cart.length,0,'late sync must not restore a previous sale');

 const reviewing = create();let finishRefresh;
 reviewing.orderSyncPromise = new Promise(resolve=>{finishRefresh=resolve;});
 reviewing.call = () => {throw new Error('an action from the old payment screen must stop after refresh');};
 const action = reviewing.ensureCurrentOrderActive();reviewing.orderModified='v2';finishRefresh();
 assert.equal(await action,false,'do not process an old button click after totals change in the background');

 const realtime = create();realtime.startOrderSync();
 let refreshes = 0;realtime.scheduleOrderSync = () => {refreshes++;};
 events.doc_update({doctype:'POS Order', name:'ORDER-1', modified:'v2'});
 events.doc_update({doctype:'POS Order', name:'OTHER', modified:'v2'});
 assert.equal(refreshes,1,'only refresh the order open on this register');
 let polls = 0;realtime.syncCurrentOrder = () => {polls++;};
 poll();assert.equal(polls,1,'polling recovers missed socket updates');
 context.document.visibilityState='hidden';poll();assert.equal(polls,1);
 context.document.visibilityState='visible';listeners.focus();assert.equal(polls,2);
 assert(subscriptions.includes('ORDER-1'));realtime.stopOrderSync();
 console.log('PASS: realtime refresh, polling recovery, three-way draft merge, conflict handling and stale-response isolation.');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
