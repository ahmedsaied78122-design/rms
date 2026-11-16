const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const context = { frappe: { pages: { 'point-of-sale': {} } }, __: value => value };
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, 'point_of_sale.js'), 'utf8') + '\nglobalThis.POS=RMSPointOfSale;', context);
function register() {
 const pos = Object.create(context.POS.prototype);
 pos.state = { cart: [], products: [], order_status: 'Open' };
 pos.ensureCurrentOrderActive = async () => true;
 pos.renderCart = pos.saveDraft = () => {};
 return pos;
}
const config = { title: 'ملوخية بالأرز', price: 110, uom: 'Meal', modifier_groups: [], must_be_whole_number: true };
const add = (pos, modifiers = [], entry = {}, option = null, options = config) => pos.pushCart('MEAL', option, modifiers, options, entry);
async function run() {
 const pos = register();
 await Promise.all([add(pos), add(pos), add(pos), add(pos)]);
 assert.equal(pos.state.cart.length, 1);
 assert.equal(pos.state.cart[0].qty, 4);
 // A saved draft's row ID is retained so the server updates that same row.
 pos.state.cart[0].saved_to_order = true; pos.state.cart[0].order_item_name = 'ITEM-1';
 await add(pos);
 assert.equal(pos.state.cart.length, 1);
 assert.equal(pos.state.cart[0].qty, 5);
 assert.equal(pos.orderPayload().items[0].order_item_name, 'ITEM-1');
 assert.equal(pos.orderPayload().items[0].qty, 5);
 // Existing duplicate editable rows collapse when the same item is added again.
 pos.state.cart.push({ ...pos.state.cart[0], local_id: 'OTHER', order_item_name: 'ITEM-2', qty: 2 });
 await add(pos);
 assert.equal(pos.state.cart.length, 1);
 assert.equal(pos.state.cart[0].qty, 8);
 assert.equal(pos.state.cart[0].order_item_name, 'ITEM-1');
 await add(pos, [], { notes: 'No salt' });
 await add(pos, [], {}, 'OTHER-OPTION');
 await add(pos, [], {}, null, { ...config, price: 120 });
 assert.equal(pos.state.cart.length, 4, 'notes, product options and different prices remain distinct');
 const modifiers = [{ modifier_group: 'SAUCES', modifier_product: 'A', qty: 1 }, { modifier_group: 'SAUCES', modifier_product: 'B' }];
 const configured = register();
 await add(configured, modifiers);
 await add(configured, [...modifiers].reverse());
 assert.equal(configured.state.cart.length, 1, 'modifier selection order does not create separate rows');
 assert.equal(configured.state.cart[0].qty, 2);
 await add(configured, [{ ...modifiers[0], qty: 2 }, modifiers[1]]);
 assert.equal(configured.state.cart.length, 2, 'different modifier quantities remain distinct');
 const pricedConfig = { ...config, modifier_groups: [{ options: [{ name: 'A', selling_price: 5 }] }] };
 await add(configured, modifiers, {}, null, pricedConfig);
 assert.equal(configured.state.cart.length, 3, 'different modifier prices must not be merged');
 const reloaded = register();
 reloaded.state.cart = reloaded.mapOrderItems({ items: [{ name: 'SAVED-1', selling_product: 'MEAL',
  qty: 2, selling_price: 110, uom: 'Meal', modifiers: [
   { modifier_group: 'SAUCES', modifier_product: 'A', qty: 1, selling_price: 5 },
   { modifier_group: 'SAUCES', modifier_product: 'B', qty: 1, selling_price: 0 },
  ] }] });
 await add(reloaded, modifiers, {}, null, pricedConfig);
 assert.equal(reloaded.state.cart.length, 1, 'the same configured product merges after reloading a saved order');
 assert.equal(reloaded.state.cart[0].qty, 3);
 const fractional = register();
 await add(fractional, [], { qty: .1 }); await add(fractional, [], { qty: .2 });
 assert.equal(fractional.state.cart[0].qty, .3);
 for (const mode of ['sent', 'cross-session', 'guest-check']) {
  const locked = register(); await add(locked);
  const original = locked.state.cart[0];
  if (mode === 'sent') original.sent_to_kitchen = true;
  if (mode === 'confirmed') { locked.state.order_status = 'Confirmed'; original.saved_to_order = true; }
  if (mode === 'cross-session') { locked.state.cross_session_edit = true; original.read_only = true; original.saved_to_order = true; }
  if (mode === 'guest-check') { locked.state.order_status = 'Confirmed'; original.saved_to_order = true; locked.guestCheckState={guest_checks:[{name:'GUEST'}]}; }
  await add(locked);
  assert.equal(locked.state.cart.length, 2, mode);
  assert.equal(original.qty, 1, 'frozen/in-flight rows must not change');
 }
 const editable = register(); editable.state.order_status='Confirmed';
 await add(editable); editable.state.cart[0].saved_to_order=true; editable.state.cart[0].order_item_name='UNSENT-1';
 await add(editable); assert.equal(editable.state.cart.length,1); assert.equal(editable.state.cart[0].qty,2);
 assert.equal(editable.orderPayload().items[0].qty,2); assert.equal(editable.orderPayload().edit_pending_items,true);
 const append = register(); append.state.order_status = 'Confirmed';
 await add(append); await add(append);
 assert.equal(append.state.cart.length, 1, 'new unsaved additions can merge before they are sent');
 assert.equal(append.state.cart[0].qty, 2);
 console.log('PASS: repeated products increase one row, saved IDs persist, identical drafts consolidate, options/notes stay distinct and prepared rows are protected.');
}
run().catch(error => { console.error(error); process.exitCode=1; });
