const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const cache = new Map([['_page:point-of-sale', 'old'], ['_page:kitchen-display', 'old'], ['saved-cart', 'keep']]);
let route = [], modal = false;
const context = {
 window: {location: {pathname: '/app/home'}},
 document: {readyState: 'loading', addEventListener() {}, querySelector: () => modal ? {} : null},
 localStorage: {getItem: k => cache.get(k), setItem: (k, v) => cache.set(k, v), removeItem: k => cache.delete(k)},
 frappe: {
  boot: {user: {name: 'Administrator', full_name: '<img onerror=boom>'}}, session: {user: 'Administrator'},
  router: {slug: s => s.toLowerCase().replaceAll(' ', '-')},
  get_route: () => route,
  get_meta: name => ({module: name === 'Selling Product' ? 'Selling' : 'RMS'}),
  utils: {escape_html: s => s.replaceAll('<', '&lt;').replaceAll('>', '&gt;')},
  ui: {},
 },
 __: (text, args = []) => text.replace(/\{(\d+)\}/g, (_, i) => args[i]),
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(__dirname + '/rms_desk.js', 'utf8'), context);
const shell = Object.create(context.window.RMSManagementShell.prototype);
const pages = [
 {name: 'Home', public: 1}, {name: 'Selling', module: 'Selling', public: 1},
 {name: 'My Space', public: 0}, {name: 'Hidden', is_hidden: '1'},
 {name: 'Forbidden', has_access: false}, {name: 'Forbidden 2', has_access: '0'},
];
context.frappe.boot.allowed_workspaces = pages;
assert.deepEqual(Array.from(shell.getWorkspaces(), p => p.name), ['Home', 'Selling', 'My Space']);
context.frappe.workspace = {all_pages: []};
assert.equal(shell.getWorkspaces().length, 0, 'an authoritative empty permission list must not fall back to boot data');
context.frappe.workspace.all_pages = pages;
assert.equal(shell.workspacePath(pages[2]), 'private/my-space');
assert.equal(shell.workspacePath(pages[1]), 'selling');
assert.equal(shell.label({name:'ERPNext Settings'}), 'Business settings');
assert.equal(cache.get('saved-cart'), 'keep');
assert.equal(cache.has('_page:point-of-sale'), false);
for (const name of ['point-of-sale', 'kitchen-display', 'table-management']) {
 route = [name]; context.window.location.pathname = '/app/' + name;
 assert.equal(shell.routeState().active, false, name + ' keeps its existing fullscreen layout');
 route = []; assert.equal(shell.routeState().active, false, 'URL fallback protects initial page load');
}
context.window.location.pathname = '/app/selling-product'; route = ['List', 'Selling Product', 'List'];
assert.equal(shell.routeState().active, true);
assert.equal(shell.routeState().workspace, false);
assert.equal(shell.activeWorkspace(pages, shell.routeState()), 'Selling');
route = ['Form', 'Selling Product', 'point-of-sale'];
assert.equal(shell.routeState().active, true, 'a document name matching a fullscreen page must not hide Management');
route = ['Workspaces', 'Home'];
assert.equal(shell.routeState().workspace, true);
assert.equal(shell.activeWorkspace(pages, shell.routeState()), 'Home');
route = ['private', 'My Space'];
assert.equal(shell.activeWorkspace(pages, shell.routeState()), 'My Space');
route = ['query-report', 'POS Sales Summary'];
context.frappe.query_report = {report_doc: {module: 'Selling'}};
assert.equal(shell.activeWorkspace(pages, shell.routeState()), 'Selling');
shell.drawerOpen = true; shell.compact = {matches: true};
let closeArgs, prevented = 0;
shell.setDrawerOpen = (...args) => {closeArgs = args;};
const key = (value, extra = {}) => ({key: value, preventDefault() {prevented++;}, stopPropagation() {}, ...extra});
modal = true;
assert.equal(shell.handleKey(key('Escape')), false, 'leave Escape to an open native dialog');
assert.equal(closeArgs, undefined);
modal = false;
assert.equal(shell.handleKey(key('Escape')), true);
assert.deepEqual(closeArgs, [false, true], 'Escape closes and returns focus to the menu button');
closeArgs = null;
shell.handleKey(key('g', {ctrlKey:true}));
assert.deepEqual(closeArgs, [false], 'the native global search shortcut releases the drawer');
let focused;
const first = {getClientRects: () => [1], focus() {focused = 'first';}};
const last = {getClientRects: () => [1], focus() {focused = 'last';}};
const hidden = {getClientRects: () => [], focus() {throw Error('hidden focus');}};
shell.sidebar = {querySelectorAll: () => [first, hidden, last]};
context.document.activeElement = last;
assert.equal(shell.handleKey(key('Tab')), true); assert.equal(focused, 'first');
context.document.activeElement = first;
assert.equal(shell.handleKey(key('Tab', {shiftKey:true})), true); assert.equal(focused, 'last');
shell.drawerOpen = false;
assert.equal(shell.handleKey(key('Tab')), false, 'closed navigation does not intercept keyboard actions');
console.log('PASS: permitted workspaces, private routes, POS isolation, saved-cart safety and accessible drawer keyboard behavior.');

async function testLanguageSwitch() {
 const requests=[];let reloads=0,messages=0;
 context.window.location.reload=()=>{reloads++;};
 context.frappe.call=async options=>{requests.push(options);return {message:{language:options.args.language}};};
 context.frappe.msgprint=()=>{messages++;};
 shell.active=true;shell.changingLanguage=false;shell.setSearchOpen=()=>{};
 context.frappe.boot.lang='en';
 await shell.switchLanguage();
 assert.equal(requests[0].method,'rms.interface_preferences.set_language');
 assert.equal(requests[0].type,'POST');assert.deepEqual(Object.keys(requests[0].args),['language']);
 assert.equal(requests[0].args.language,'ar');assert.equal(reloads,1);
 await shell.switchLanguage();assert.equal(requests.length,1,'double clicks must not send another preference write');
 shell.changingLanguage=false;context.frappe.boot.lang='ar';await shell.switchLanguage();
 assert.equal(requests[1].args.language,'en');assert.equal(reloads,2);
 shell.changingLanguage=false;context.window.cur_frm={is_dirty:()=>true};
 await shell.switchLanguage();assert.equal(requests.length,2);assert.equal(messages,1,'unsaved documents must not be reloaded');
 context.window.cur_frm=null;context.window.locals={Item:{draft:{__unsaved:1}}};
 await shell.switchLanguage();assert.equal(requests.length,2);assert.equal(messages,2,'background drafts are protected');
 context.window.locals={};route=['Workspaces','Home'];context.frappe.workspace.is_read_only=false;
 await shell.switchLanguage();assert.equal(requests.length,2);assert.equal(messages,3,'workspace editing is protected');
 context.frappe.workspace.is_read_only=true;
 context.frappe.call=async()=>{throw Error('Network unavailable');};
 await shell.switchLanguage();assert.equal(reloads,2);assert.equal(shell.changingLanguage,false,'errors must leave the current page usable');
 console.log('PASS: self-language requests, Arabic/English targets, double-click protection, unsaved document/layout protection and error recovery.');
}
testLanguageSwitch().catch(error=>{console.error(error);process.exitCode=1;});
