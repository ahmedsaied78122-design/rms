const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
let dialog;
const check = { checked: true, dataset: { returnSelect: '0' }, closest: () => ({ classList: { toggle() {} } }) };
class Element {
 constructor(node) {
  this.children = new Map(); this.handlers = {};
  this[0] = node || { value: '', attributes: {}, setAttribute(key, value) { this.attributes[key] = value; },
   removeAttribute(key) { delete this.attributes[key]; }, scrollIntoView() {},
   querySelectorAll: selector => selector.includes('data-return-select') ? [check] : [],
   querySelector: selector => selector.includes('data-return-qty') ? { value: '1' } : { checked: false } };
 }
 find(selector) { if (!this.children.has(selector)) this.children.set(selector, new Element()); return this.children.get(selector); }
 on(event, selector, fn) { this.handlers[`${event}:${typeof selector === 'string' ? selector : ''}`] = fn || selector; return this; }
 each() { return this; }
 text() { return this; }
 prop(key, value) { this[0][key] = value; return this; }
 attr(key, value) { this[0].setAttribute(key, value); return this; }
 removeClass() { return this; }
 addClass() { return this; }
 trigger(event) { this.handlers[`${event}:`]?.({ currentTarget: this[0] }); return this; }
}
const context = {
 frappe: { pages: { 'point-of-sale': {} }, ui: { Dialog: class {
  constructor(options) { Object.assign(this, options); this.$wrapper = new Element(); this.values = {}; dialog = this; }
  set_value(key, value) { this.values[key] = value; }
  get_value(key) { return this.values[key]; }
  show() {} hide() {} enable_primary_action() {} disable_primary_action() {}
 } }, msgprint() { throw new Error('Missing reason should be identified inline'); } },
 __: value => value, $: node => new Element(node),
 window: { requestAnimationFrame: callback => callback(), setTimeout: callback => callback() },
 document: { activeElement: null },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, 'point_of_sale.js'), 'utf8') + '\nglobalThis.POS=RMSPointOfSale;', context);
async function run() {
 const pos = Object.create(context.POS.prototype), calls = [];
 pos.escape = value => String(value || ''); pos.currency = value => String(value);
 pos.showError = error => { throw error; };
 pos.call = async (method, args) => { calls.push({ method, args }); return { refund_total: 100 }; };
 pos.openReturnPayments = async (...args) => { pos.paymentArgs = args; };
 await pos.openReturnItems({ name: 'INV-1', returnable_lines: [
  { name: 'LINE-1', item_code: 'MEAL', qty: 1, rate: 100, uom: 'Meal', must_be_whole_number: true },
 ] }, [], [{ name: 'REASON-1', reason: 'Customer changed their mind' }]);
 const field = dialog.fields.find(field => field.fieldname === 'action_reason');
 assert.equal(field.label, 'Return reason');
 assert.ok(!field.reqd, 'hidden storage field must not intercept validation with a generic missing-values dialog');
 await dialog.primary_action({});
 assert.equal(calls.length, 0, 'do not preview an incomplete return');
 assert.equal(dialog.$wrapper.find('[data-return-reason-error]')[0].hidden, false);
 assert.equal(dialog.$wrapper.find('[data-return-reason-search]')[0].attributes['aria-invalid'], 'true');
 const option = { dataset: { returnReason: 'REASON-1' }, textContent: 'Customer changed their mind', attributes: {},
  setAttribute(key, value) { this.attributes[key] = value; } };
 dialog.$wrapper.handlers['click:[data-return-reason]']({ currentTarget: option });
 assert.equal(dialog.get_value('action_reason'), 'REASON-1');
 assert.equal(dialog.$wrapper.find('[data-return-reason-error]')[0].hidden, true);
 dialog.$wrapper.find('[data-return-reason-search]').trigger('focus');
 assert.equal(dialog.get_value('action_reason'), 'REASON-1', 'refocusing the reason must retain the selection');
 await dialog.primary_action({ action_reason: dialog.get_value('action_reason') });
 assert.equal(calls[0].method, 'preview_pos_return');
 assert.equal(calls[0].args.action_reason, 'REASON-1');
 assert.equal(pos.paymentArgs[2], 'REASON-1');
 console.log('PASS: missing return reason is identified inline, no incomplete preview, selection survives focus and reaches the refund preview.');
}
run().catch(error => { console.error(error); process.exitCode=1; });
