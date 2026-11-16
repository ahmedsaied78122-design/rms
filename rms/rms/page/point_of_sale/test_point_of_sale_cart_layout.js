const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const context = { frappe: { pages: { 'point-of-sale': {} }, user_roles: ['POS Manager'] }, __: text => text };
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, 'point_of_sale.js'), 'utf8')+'\nglobalThis.POS=RMSPointOfSale;', context);
const pos = Object.create(context.POS.prototype), output = {};
pos.page = { main: { find(selector) {
 const value = output[selector] ||= {};
 return { html(html) { value.html=html; return this; }, text(text) { value.text=text; return this; }, prop(key,v) { value[key]=v; return this; } };
} } };
pos.escape = value => String(value ?? ''); pos.currency = value => String(value);
pos.state = { order_name:'ORDER-6', order_status:'Confirmed', permissions:{can_cancel_orders:true,can_checkout:true}, session:{name:'SESSION-1'}, cart:[
 {order_item_name:'SENT-1',title:'Prepared meal',qty:4,price:50,uom:'Nos',sent_to_kitchen:true,saved_to_order:true},
 {local_id:'NEW-1',title:'New meal',qty:1,price:100,sent_to_kitchen:false},
 {order_item_name:'CANCELLED-1',title:'Cancelled meal',qty:2,cancelled_qty:2,price:50,sent_to_kitchen:true},
] };
pos.renderCart();
let html = output['[data-role="cart"]'].html;
assert.ok(html.indexOf('is-pending') < html.indexOf('is-confirmed'), 'new additions must appear before prepared items');
assert.ok(html.indexOf('New meal') < html.indexOf('Prepared meal'));
assert.match(html, /data-action="remove" data-index="1"/, 'grouping must keep the original cart index for removing a new row');
assert.match(html, /data-action="quantity" data-index="1"/, 'quantity controls must point at the new row, not the visually preceding group');
assert.equal((html.match(/data-action="remove"/g)||[]).length,1, 'prepared rows cannot be removed through draft controls');
assert.ok(!html.includes('data-action="cancel-confirmed-item"'), 'use one bulk control instead of a cancellation button on each row');
assert.match(html, /<details class="rms-cart-section is-cancelled">/, 'cancelled history is collapsed');
assert.equal(pos.cartTab,'pending');
assert.match(html, /data-cart-panel="confirmed" hidden/,'confirmed items have a separate hidden panel');
assert.match(output['[data-role="cart-tabs"]'].html, /aria-selected="true" data-action="cart-tab" data-tab="pending"/);
assert.equal(output['[data-role="cart-actions"]'].hidden,true,'Void only appears in the confirmed tab');
pos.cartTab='confirmed'; pos.renderCart();
assert.equal(output['[data-role="cart-actions"]'].hidden,false);
assert.match(output['[data-role="cart"]'].html, /data-cart-panel="pending" hidden/);
pos.renderCart(); assert.equal(pos.cartTab,'confirmed','autosave and rerenders retain the selected tab');
pos.cartTab='pending'; pos.renderCart();
assert.equal(output['[data-role="ticket"]'].text,'In progress','do not repeat the long order ID in the header badge');
assert.match(output['[data-role="cart-actions"]'].html, />Void<\/button>/);
assert.ok(!html.includes('Nos'), 'cart rows omit units of measure');
// Autosave persists additions before they are sent to preparation. Persistence
// must never change their confirmation status or hide their controls.
Object.assign(pos.state.cart[1], {order_item_name:'SAVED-NEW',saved_to_order:true});
pos.renderCart();
html = output['[data-role="cart"]'].html;
assert.match(html, /data-cart-confirmation="pending" data-cart-item="SAVED-NEW"/);
assert.ok(html.indexOf('New meal') < html.indexOf('is-confirmed'));
assert.equal(output['[data-action="checkout"]'].text,'Confirm');
assert.match(html, /data-action="quantity" data-index="1"/, 'saved unsent additions remain editable');
assert.equal(pos.orderPayload().edit_pending_items,true);
assert.equal(pos.orderPayload().items[0].order_item_name,'SAVED-NEW');
pos.saveDraft = () => {};
pos.updateQuantity({dataset:{quantity:'1'},value:'3'});
assert.equal(pos.state.cart[1].qty,3);
assert.equal(pos.orderPayload().items[0].qty,3,'quantity edits to a saved pending row reach the save payload');
pos.renderFields = pos.watchCurrentOrder = () => {};
const snapshot = {name:'ORDER-6',status:'Confirmed',modified:'v2',items:[
 {name:'SENT-1',selling_product:'MEAL-1',title:'Prepared meal',qty:4,selling_price:50,uom:'Nos',sent_to_kitchen:1},
 {name:'SAVED-NEW',selling_product:'MEAL-2',title:'New meal',qty:1,selling_price:100,uom:'Nos',sent_to_kitchen:0},
]};
pos.applyOrderSnapshot(snapshot);
html = output['[data-role="cart"]'].html;
assert.equal(pos.state.cart.length,2,'synchronization retains saved additions');
assert.match(html, /data-cart-confirmation="pending" data-cart-item="SAVED-NEW"/);
assert.equal(output['[data-action="checkout"]'].text,'Confirm');
pos.state.cart[1].read_only = true; pos.renderCart();
assert.match(output['[data-role="cart"]'].html, /data-cart-confirmation="pending" data-cart-item="SAVED-NEW"/);
snapshot.items[1].sent_to_kitchen = 1; snapshot.modified='v3';
pos.applyOrderSnapshot(snapshot);
assert.ok(!output['[data-role="cart"]'].html.includes('is-pending'), 'only sending to preparation confirms the addition');
assert.equal(output['[data-action="checkout"]'].text,'Take Payment');
assert.equal(pos.cartTab,'confirmed','sending the final pending row opens the confirmed tab');
pos.guestCheckState = {guest_checks:[{name:'GUEST-1'}]}; pos.renderCart();
assert.equal(output['[data-role="cart-actions"]'].hidden,true, 'confirmed guest allocations protect the cancellation flow');
pos.guestCheckState = null; context.frappe.user_roles=['POS Cashier']; pos.renderCart();
assert.equal(output['[data-role="cart-actions"]'].hidden,false,'cashiers can request void with backend manager authorization');
context.frappe.user_roles=['POS Manager']; pos.state.order_status='Paid'; pos.renderCart();
assert.equal(output['[data-role="cart-actions"]'].hidden,true);
assert.equal(output['[data-action="checkout"]'].disabled,true);
console.log('PASS: new items first, stable row actions, compact confirmed rows, one bulk action, collapsed cancellations and permission restrictions.');

// Display the payable amount while preserving the exact tax/discount calculation base.
pos.state.order_name='RMS-ORD-2026-00016';pos.state.order_status='Confirmed';
pos.state.brand='BRAND-1';pos.state.brands=[{name:'BRAND-1',pos_rounding_method:'Nearest'}];
pos.state.totals={subtotal:245,tax_total:34.3,grand_total:279.3};
for (const [method,total,adjustment,hidden] of [['Nearest','279',-.3,false],['Round Up','280',.7,false],['Round Down','279',-.3,false],['No Rounding','279.3',0,true]]) {
 pos.state.brands[0].pos_rounding_method=method;pos.renderCart();
 assert.equal(output['[data-role="total"]'].text,total,method);
 assert.equal(output['[data-role="rounding-adjustment"]'].text,String(adjustment));
 assert.equal(output['[data-role="rounding-row"]'].hidden,hidden);
 assert.equal(pos.state.totals.grand_total,279.3,'rounding must not overwrite accounting or discount totals');
}
assert.equal(output['[data-role="cart-title"]'].text,'16');
pos.state.order_name='maadi-09112026-0023';pos.renderCart();
assert.equal(output['[data-role="cart-title"]'].text,'23');assert.equal(pos.orderPayload().name,'maadi-09112026-0023','API requests must keep the complete ID');
for (const [name,short] of [['nasr-10112026-0001','1'],['custom-reference','custom-reference'],['0000','0']]) assert.equal(pos.orderNumber(name),short);
pos.state.brands[0].pos_rounding_method='Nearest';pos.state.totals.grand_total=280;pos.renderCart();assert.equal(output['[data-role="rounding-row"]'].hidden,true);
for (const [method,expected] of [['Nearest',-80],['Round Up',-81],['Round Down',-80],['No Rounding',-80.49]]) assert.equal(pos.roundPosPayable(-80.49,method),expected,'negative parity with server rounding');
console.log('PASS: rounded order summary matches payment, adjustment is explicit, exact totals stay intact, short order labels preserve complete API identifiers.');
