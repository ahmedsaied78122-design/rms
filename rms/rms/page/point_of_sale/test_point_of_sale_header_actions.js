const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = {frappe: {pages: {'point-of-sale': {}}}, __: text => text, window: {innerWidth: 390, innerHeight: 844}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, 'point_of_sale.js'), 'utf8') + '\nglobalThis.POS = RMSPointOfSale;', context);
let active;
const container = {};
function button(action, capability) {
 return {dataset: {action, ...(capability ? {capability} : {})}, hidden: false, disabled: false,
  focus() {active = this;}, closest(selector) {return selector === '[data-more-actions]' ? container : null;}};
}
const items = [button('expenses'), button('returns'), button('sales-history', 'can_view_sales_history'),
 button('operation-approvals', 'can_approve_discount'), button('my-account'), button('language'), button('switch-apps'), button('logout')];
const kitchen = button('kitchen-display', 'can_access_kitchen');
const toggle = {setAttribute(name, value) {this[name] = value;}, focus() {active = this;},
 closest(selector) {return ['[data-more-actions]', '[data-more-toggle]'].includes(selector) ? container : null;}};
const menu = {hidden: true, style: {}, getBoundingClientRect: () => ({left: 100, right: 350, top: 140}), querySelectorAll: () => items};
const root = {querySelector: selector => selector === '[data-actions-menu]' ? menu : selector === '[data-more-toggle]' ? toggle : null};
const main = Object.assign([root], {find(selector) {
 const selected = selector === '[data-capability]' ? [...items, kitchen].filter(item => item.dataset.capability)
  : [...selector.matchAll(/data-action="([^"]+)"/g)].flatMap(match => items.filter(item => item.dataset.action === match[1]));
 return {prop(name, value) {selected.forEach(item => item[name] = value);}, each(callback) {selected.forEach((item, index) => callback(index, item));}};
}});
const pos = Object.create(context.POS.prototype);
pos.page = {main};
pos.state = {store: 'STORE-1', session: {status: 'Open'}, permissions: {can_view_sales_history: true, can_approve_discount: true, can_access_kitchen: true}};
function key(value, target = active || toggle) {
 const event = {key: value, target, prevented: false, stopped: false, preventDefault() {this.prevented = true;}, stopPropagation() {this.stopped = true;}};
 return {handled: pos.handleActionsMenuKey(event), event};
}
pos.renderHeaderActions();
pos.setActionsMenuOpen(true, 'first');
assert.equal(menu.style.maxHeight, '692px', 'menu height fits below the header');
assert.equal(menu.hidden, false);assert.equal(toggle['aria-expanded'], 'true');assert.equal(active, items[0]);
key('ArrowDown');assert.equal(active, items[1]);
key('End');assert.equal(active, items.at(-1));
key('Home');assert.equal(active, items[0]);
const escape = key('Escape');assert.equal(escape.handled, true);assert.equal(escape.event.stopped, true);assert.equal(menu.hidden, true);assert.equal(active, toggle);
const closedEscape = key('Escape');assert.equal(closedEscape.handled, false);assert.equal(closedEscape.event.prevented, false, 'closed menu must not consume Escape intended for another dialog');
pos.state.permissions = {can_view_sales_history: false, can_approve_discount: false, can_access_kitchen: false};
pos.renderHeaderActions();
assert.equal(items[2].hidden, true);assert.equal(items[3].hidden, true);assert.equal(kitchen.hidden, true);
key('ArrowDown', toggle);assert.equal(active, items[0]);key('ArrowDown');assert.equal(active, items[1]);key('ArrowDown');assert.equal(active, items[4], 'skip hidden role-restricted entries');
pos.state.session = null;pos.renderHeaderActions();pos.setActionsMenuOpen(true, 'first');
assert.equal(items[0].disabled, true);assert.equal(items[1].disabled, true);assert.equal(active, items[4], 'skip session-only actions when no shift is open');
console.log('PASS: grouped actions, keyboard focus, Escape isolation, live role visibility and session availability.');

async function accountTests() {
 const events = [];
 context.frappe.session = {user: 'cashier@example.com', user_fullname: 'Cashier'};
 context.frappe.boot = {user: {full_name: '<Cashier & Manager>'}, lang: 'en'};
 context.frappe.utils = {
  escape_html: value => value.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  is_rtl: () => context.frappe.boot.lang === 'ar',
 };
 let html;
 main.html = value => {html = value;};
 pos.mount();
 const englishMenu = html.slice(html.indexOf('data-actions-menu'), html.indexOf('</header>'));
 assert.ok(html.includes('&lt;Cashier &amp; Manager&gt;'));
 assert.ok(!html.includes('<Cashier & Manager>'), 'user identity must be escaped');
 assert.match(englishMenu, /dir="ltr"/);
 assert.ok(!/[\u0600-\u06ff]/u.test(englishMenu.replace('العربية', '')), 'English account menu contains no hardcoded Arabic');
 const translations = Object.fromEntries(fs.readFileSync(path.join(__dirname, '../../../translations/ar.csv'), 'utf8').trim().split(/\r?\n/).map(line => line.split(',')));
 context.__ = text => translations[text] || text;
 context.frappe.boot.lang = 'ar';pos.mount();
 for (const label of ['قائمة المستخدم', 'المصروفات', 'الموافقات', 'حسابي', 'تسجيل الخروج']) assert.ok(html.includes(label), label);
 assert.match(html, /dir="rtl"/);
 context.__ = text => text;context.frappe.boot.lang = 'en';
 context.frappe.set_route = (...route) => events.push(['route', ...route]);
 context.frappe.app = {logout: () => events.push('logout')};
 pos.flushDraftSave = async () => {events.push('save');};
 pos.ensureCurrentOrderActive = async () => {throw Error('Account actions must not depend on order status');};
 pos.showError = error => {events.push(error.message);};
 pos.showMyAccount = () => events.push('in-pos-account');
 await pos.onAction('my-account');
 assert.equal(JSON.stringify(events), JSON.stringify(['in-pos-account']), 'My Account opens in place without routing or saving the active draft');
 assert.ok(!html.includes('POS Settings'));assert.ok(!html.includes('data-action="sale-settings"'));
 assert.equal((html.match(/data-language=/g)||[]).length,2);
 events.length = 0;await pos.onAction('logout');
 assert.equal(JSON.stringify(events), JSON.stringify(['save', 'logout']), 'save before standard logout without closing the cashier session');
 pos.flushDraftSave = async () => {throw Error('Save failed');};
 events.length = 0;await pos.onAction('logout');
 assert.equal(JSON.stringify(events), JSON.stringify(['Save failed']), 'failed save keeps the user signed in');
 context.frappe.ui = {Dialog: class {constructor() {throw Error('Language must not open a dialog');}}};
 context.frappe.db = {set_value: async (...args) => {events.push(args);}};
 context.window.location = {reload: () => events.push('reload')};
 events.length = 0;await pos.changeLanguage('en');
 assert.equal(JSON.stringify(events), JSON.stringify([]), 'unchanged language does not write or reload');
 await pos.changeLanguage('fr');assert.equal(events.length,0,'only Arabic and English can be selected');
 events.length = 0;await pos.changeLanguage('ar');
 assert.equal(JSON.stringify(events), JSON.stringify(['Save failed']), 'failed draft save prevents language write and reload');
 assert.equal(pos.languageChangePending,false);
 pos.flushDraftSave = async () => {events.push('save');};
 events.length = 0;await pos.changeLanguage('ar');
 assert.equal(JSON.stringify(events), JSON.stringify(['save', ['User', 'cashier@example.com', 'language', 'ar'], 'reload']));
 context.frappe.db.set_value=async()=>{throw Error('Language save failed');};
 events.length=0;await pos.changeLanguage('ar');assert.equal(JSON.stringify(events),JSON.stringify(['save','Language save failed']));
 assert.equal(pos.languageChangePending,false,'failed writes re-enable language choices');
 console.log('PASS: translated English/Arabic account menu, escaped identity, in-POS account, direct Arabic/English choice, save-before-logout and language reload, failed-save protection.');
}
accountTests().catch(error => {console.error(error);process.exitCode = 1;});
