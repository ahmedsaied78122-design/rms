const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const dialogs = [];
class Element {
 constructor() { this.children = new Map(); this.handlers = {}; this.values = []; }
 find(selector) { if (!this.children.has(selector)) this.children.set(selector, new Element()); return this.children.get(selector); }
 on(event, callback) { this.handlers[event] = callback; return this; }
 attr() { return this; }
 addClass() { return this; }
 prop(key, value) { this[key] = value; return this; }
 val(value) { if (value === undefined) return this.value || ''; this.value = value; return this; }
 show() { return this; }
 toggle() { return this; }
 trigger() { return this; }
 html(value) { this.content = value; return this; }
 map(callback) { return { get: () => this.values.map((value, index) => callback(index, { value })) }; }
}
class Dialog {
 constructor(options) {
  Object.assign(this, options);
  this.fields_dict = {};
  this.$wrapper = new Element();
  for (const field of this.fields) this.fields_dict[field.fieldname] = { df: field, $input: new Element(), $wrapper: new Element() };
  dialogs.push(this);
 }
 set_df_property(field, property, value) { this.fields_dict[field].df[property] = value; }
 show() { this.is_visible = true; }
 hide() { this.is_visible = false; this.onhide?.(); }
 disable_primary_action() { this.disabled = true; }
 enable_primary_action() { this.disabled = false; }
}
const context = { frappe: { pages: { 'point-of-sale': {} }, ui: { Dialog } }, __: v => v, $: v => v, setTimeout, clearTimeout };
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, 'point_of_sale.js'), 'utf8') + '\nglobalThis.POS = RMSPointOfSale;', context);
async function run() {
 const pos = Object.create(context.POS.prototype);
 pos.state = { store: 'STORE-1' };
 pos.escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
 pos.showError = error => { throw error; };
 for (const phone of ['01012345678', '+20 (10) 1234-5678', '٠١٠١٢٣٤٥٦٧٨', '۰۱۰۱۲۳۴۵۶۷۸']) {
  const values = pos.customerSearchDefaults(phone);
  assert.equal(values.customer_name, '');
  assert.ok(values.mobile_no.startsWith('0') || values.mobile_no.startsWith('+'));
 }
 assert.equal(pos.customerSearchDefaults('  أحمد علي ').customer_name, 'أحمد علي');
 assert.equal(pos.customerSearchDefaults('Ahmed 2').mobile_no, '');
 let selected, reopened = 0;
 const chooser = { hide() {}, show() { reopened++; }, selectCustomer(customer) { selected = customer.name; } };
 const click = (extras, selector, dataset = {}) => extras.find(selector).handlers.click({ currentTarget: { dataset } });
 const inputPhone = (extras, index, value) => extras.find('[data-phone-index]').handlers.input({ currentTarget: { dataset: { phoneIndex: String(index) }, value } });
 const defaultPhone = (extras, index) => extras.find('[data-default-phone]').handlers.change({ currentTarget: { dataset: { defaultPhone: String(index) } } });
 const defaultAddress = (extras, index) => extras.find('[data-default-address]').handlers.change({ currentTarget: { dataset: { defaultAddress: String(index) } } });
 const create = pos.createCustomer(chooser, '01012345678');
 const extras = create.fields_dict.customer_extras.$wrapper;
 assert.equal(create.size, 'small');
 assert.ok(extras.find('.rms-customer-phones').content.includes('value="01012345678"'));
 assert.equal(create.fields.filter(field => field.reqd).length, 1);
 click(extras, '[data-add-phone]');
 inputPhone(extras, 1, '01011111111');
 defaultPhone(extras, 1);
 click(extras, '[data-add-address]');
 const address = dialogs.at(-1);
 assert.equal(address.fields_dict.address_line1.df.reqd, 1);
 assert.equal(address.fields_dict.city.df.reqd, 1);
 address.primary_action({ address_line1: 'Home', city: 'Cairo' });
 click(extras, '[data-add-address]');
 dialogs.at(-1).primary_action({ address_line1: 'Office', city: 'Giza' });
 defaultAddress(extras, 1);
 click(extras, '[data-edit-address]', { editAddress: '0' });
 assert.equal(dialogs.at(-1).fields_dict.address_line1.df.default, 'Home');
 dialogs.at(-1).primary_action({ address_line1: 'Updated Home', city: 'Cairo' });
 pos.call = async (method, values) => {
  assert.equal(method, 'save_customer_details');
  assert.equal(values.customer_name, 'Ahmed');
  assert.equal(values.store, 'STORE-1');
  assert.equal(values.customer, undefined);
  assert.deepEqual(Array.from(values.phones, row => row.phone), ['01012345678', '01011111111']);
  assert.deepEqual(Array.from(values.phones, row => row.is_default), [false, true]);
  assert.deepEqual(Array.from(values.addresses, row => row.address_line1), ['Updated Home', 'Office']);
  assert.deepEqual(Array.from(values.addresses, row => row.is_default), [false, true]);
  return { name: 'CUSTOMER-1' };
 };
 await create.primary_action({ customer_name: 'Ahmed' });
 assert.equal(selected, 'CUSTOMER-1');
 assert.equal(create.is_visible, false);
 assert.equal(create.disabled, false);
 assert.equal(reopened, 1);
 const details = { name: 'CUSTOMER-1', customer_name: 'Ahmed', mobile_no: '01012345678',
  phone_rows: [
   { name: 'PHONE-1', contact: 'CONTACT-1', phone: '01012345678', is_default: true },
   { name: 'PHONE-2', contact: 'CONTACT-1', phone: '01011111111', is_default: false },
  ], addresses: [
   { name: 'ADDRESS-1', address_line1: '<Home>', city: 'Cairo', is_default: true },
   { name: 'ADDRESS-2', address_line1: 'Office', city: 'Giza', is_default: false },
  ] };
 pos.call = async (method, values) => {
  assert.equal(method, 'get_customer_details');
  assert.equal(values.customer, 'CUSTOMER-1');
  return details;
 };
 const edit = await pos.editCustomer(chooser, 'CUSTOMER-1');
 assert.equal(edit.title, 'Edit Customer');
 assert.equal(edit.fields_dict.customer_name.df.default, 'Ahmed');
 const editExtras = edit.fields_dict.customer_extras.$wrapper;
 assert.ok(editExtras.find('.rms-customer-phones').content.includes('value="01011111111"'));
 assert.ok(editExtras.find('.rms-customer-addresses').content.includes('&lt;Home>'));
 assert.ok(editExtras.find('.rms-customer-addresses').content.includes('data-edit-address="0"'));
 inputPhone(editExtras, 1, '01022222222');
 defaultPhone(editExtras, 1);
 click(editExtras, '[data-edit-address]', { editAddress: '1' });
 assert.equal(dialogs.at(-1).title, 'Edit Address');
 assert.equal(dialogs.at(-1).fields_dict.city.df.default, 'Giza');
 dialogs.at(-1).primary_action({ address_line1: 'New office', city: 'Giza' });
 defaultAddress(editExtras, 1);
 pos.call = async (method, values) => {
  assert.equal(method, 'save_customer_details');
  assert.equal(values.customer, 'CUSTOMER-1');
  assert.equal(values.customer_name, 'Ahmed Ali');
  assert.equal(values.phones[1].name, 'PHONE-2');
  assert.equal(values.phones[1].phone, '01022222222');
  assert.deepEqual(Array.from(values.phones, row => row.is_default), [false, true]);
  assert.equal(values.addresses[1].name, 'ADDRESS-2');
  assert.equal(values.addresses[1].address_line1, 'New office');
  assert.deepEqual(Array.from(values.addresses, row => row.is_default), [false, true]);
  return { name: 'CUSTOMER-1' };
 };
 await edit.primary_action({ customer_name: 'Ahmed Ali' });
 assert.equal(edit.is_visible, false);
 // Cancelled editing does not mutate the fetched details or saved defaults.
 assert.equal(details.phone_rows[1].phone, '01011111111');
 assert.equal(details.addresses[1].address_line1, 'Office');
 // Failed saves keep edits open for retry.
 edit.show();
 let errorShown = false;
 pos.showError = () => { errorShown = true; };
 pos.call = async () => { throw new Error('Save failed'); };
 await edit.primary_action({ customer_name: 'Ahmed Ali' });
 assert.ok(errorShown);
 assert.equal(edit.disabled, false);
 assert.equal(edit.is_visible, true);
 // The chooser exposes editing for the selected existing customer.
 pos.state.customer = null;
 pos.call = async method => { assert.equal(method, 'get_customers'); return [details]; };
 await pos.chooseCustomer();
 const picker = dialogs.at(-1), pickerRoot = picker.fields_dict.customer_picker.$wrapper;
 const editButton = pickerRoot.find('[data-edit-customer]');
 assert.equal(editButton.hidden, true);
 pickerRoot.find('.rms-customer-results').find('[data-customer-index]').handlers.click({ currentTarget: { dataset: { customerIndex: '0' } } });
 assert.equal(editButton.hidden, false);
 let editedCustomer;
 pos.editCustomer = (dialog, customer) => { assert.equal(dialog, picker); editedCustomer = customer; };
 editButton.handlers.click();
 assert.equal(editedCustomer, 'CUSTOMER-1');
 console.log('PASS: all phone fields editable; saved addresses editable; phone/address defaults selectable; IDs retained; failed saves preserve edits.');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
