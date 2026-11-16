const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const dialogs = [], messages = [];
class Dialog {
 constructor(options) {
  Object.assign(this, options); this.values = {}; this.handlers = {};
  options.fields.forEach(field => {this.values[field.fieldname] = field.default || '';});
  this.$wrapper = {addClass() {}, on: (event, selector, handler) => {this.handlers[selector] = handler;},
   find: () => ({prop() {}, text() {}})};
  dialogs.push(this);
 }
 get_value(key) {return this.values[key];}
 set_value(key, value) {this.values[key] = value;}
 show() {this.visible = true;}
 hide() {this.visible = false; this.onhide?.();}
 disable_primary_action() {} enable_primary_action() {}
}
const context = {frappe: {pages: {'point-of-sale': {}}, ui: {Dialog}, msgprint: message => messages.push(message)},
 __: text => text, console, setTimeout, clearTimeout};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, 'point_of_sale.js'), 'utf8') + '\nglobalThis.POS = RMSPointOfSale;', context);
const pending = () => new Promise(resolve => setImmediate(resolve));
async function run() {
 const pos = Object.create(context.POS.prototype), calls = [], errors = [];
 const origin = {show() {this.visible = true;}, hide() {this.visible = false;}, visible: true};
 pos.showError = error => errors.push(error.message);
 pos.call = async (method, args) => {calls.push({method, args}); return {name: 'ORDER-1'};};
 const args = {order_name: 'ORDER-1', items: '[{"item_name":"ROW-1","qty":2}]', comment: 'بدون ملح', is_waste: 1};
 assert.equal((await pos.completeAuthorizedOperation('cancel_confirmed_order_items', args, origin)).name, 'ORDER-1');
 assert.equal(dialogs.length, 0, 'users with permission execute directly');
 pos.call = async (method, params) => {
  calls.push({method, args: params});
  if (method === 'request_pos_operation_approval') return {name: 'APPROVAL-1'};
  if (params.approval_password === 'wrong') throw Error('Wrong password');
  if (params.approval_password || params.approval_code) return {name: 'ORDER-1'};
  return {requires_manager_authorization: true, approvers: [{user: 'manager@example.com', full_name: 'Manager'}], operation_context: {payload: args}};
 };
 const operation = pos.completeAuthorizedOperation('cancel_confirmed_order_items', args, origin); await pending();
 const password = dialogs.at(-1); assert.equal(origin.visible, false);
 password.values.approver = 'manager@example.com'; password.values.credential = 'wrong';
 await password.primary_action(password.values);
 assert.equal(password.visible, true, 'failed approval preserves the dialog and selection');
 assert.equal(errors.at(-1), 'Wrong password');
 password.values.credential = 'temporary-test'; await password.primary_action(password.values);
 assert.equal((await operation).name, 'ORDER-1');
 assert.equal(calls.at(-1).args.comment, args.comment);assert.equal(calls.at(-1).args.items, args.items);
 assert.equal(calls.at(-1).args.approval_password, 'temporary-test');
 const returnArgs = {source_pos_invoice: 'INVOICE-1', items: '[{"qty":1}]', comment: 'كومنت المرتجع'};
 const returnOperation = pos.completeAuthorizedOperation('request_pos_return', returnArgs, origin); await pending();
 const otp = dialogs.at(-1);otp.values.approver = 'manager@example.com';otp.values.method = 'OTP';
 await otp.handlers['[data-fieldname="method"] select, [data-fieldname="approver"] select']();
 assert.equal(calls.at(-1).method, 'request_pos_operation_approval');
 assert.equal(calls.at(-1).args.approver, 'manager@example.com');
 otp.values.credential = '123456';await otp.primary_action(otp.values);await returnOperation;
 assert.equal(calls.at(-1).args.approval_code, '123456');
 assert.equal(calls.at(-1).args.comment, returnArgs.comment);
 const canceled = pos.completeAuthorizedOperation('request_pos_return', returnArgs, origin);await pending();dialogs.at(-1).hide();
 assert.equal(await canceled, null);assert.equal(origin.visible, true);
 pos.escape = value => String(value || '');
 let openedRoute;
 context.window = {rmsShowApprovalPopup: args => {openedRoute = args;}};
 pos.call = async method => {
  assert.equal(method, 'get_pending_pos_operation_approvals');
  return [{name:'APPROVAL-1', action:'POS Void', subject:'ORDER-1', requester:'cashier@example.com', status:'Issued', notification_log:'NOTIFICATION-1',
   context:{payload:{is_waste:1, comment:'تعليق', items:[{title:'Rice', qty:2}]}}}];
 };
 pos.state = {store:'STORE-1'};
 await pos.showOperationApprovals();
 const approvals = dialogs.at(-1);
 assert.match(approvals.fields[0].options, /View code in notifications/);
 assert.ok(!approvals.fields[0].options.includes('data-operation-issue='), 'issued OTP opens the manager notification');
 approvals.handlers['[data-operation-notification]']({currentTarget:{dataset:{operationNotification:'0'}}});
 assert.equal(openedRoute.notification_name, 'NOTIFICATION-1');assert.equal(openedRoute.challenge_name, 'APPROVAL-1');
 const sendButton = {disabled:false,focus() {}}, sendStatus = {isConnected:true,textContent:''};
 pos.page = {main:{0:{querySelector(selector) {return selector.includes('status') ? sendStatus : sendButton;}}}};
 pos.state = {order_name:'ORDER-1'};pos.orderModified='2026-11-05 15:00:00';
 pos.paymentDiscount = {type:'Percentage',value:0,reason:''};
 pos.paymentDiscountDraft = {type:'Percentage',value:20,reason:'Customer discount'};
 pos.paymentDiscountApprovalApprover = 'manager@example.com';
 pos.call = async (method, params) => {
  assert.equal(method,'request_pos_discount_approval_code');assert.equal(params.discount_value,20,'send the proposed discount');
  assert.equal(params.discount_reason,'Customer discount');assert.equal(params.approver,'manager@example.com');return {name:'DISCOUNT-APPROVAL-1'};
 };
 pos.renderDiscountApprovalPrompt = pos.updateDiscountApplyState = () => {};
 await pos.selectDiscountApprover('manager@example.com');assert.match(sendStatus.textContent,/تم إرسال/);assert.equal(sendButton.disabled,true);
 assert.ok(!sendStatus.textContent.includes('DISCOUNT-APPROVAL-1'));
 let sentAgain=0;pos.call=async(method,params)=>{sentAgain++;assert.equal(params.resend,1);return {name:'NEW-CODE'};};
 await pos.setDiscountApprovalMethod('Password');await pos.setDiscountApprovalMethod('OTP');assert.equal(sentAgain,0,'method switches must not request or send another code');
 await pos.requestDiscountApprovalCode(true);assert.equal(sentAgain,0,'resend is blocked during cooldown');
 for(const entry of pos.approvalDeliveries.values())entry.resendAt=Date.now()-1;
 await pos.requestDiscountApprovalCode(true);assert.equal(sentAgain,1,'explicit resend is sent after cooldown');
 await pos.authorizePendingExpense([{name:'EXPENSE-1'}],[{user:'manager@example.com',full_name:'Manager'}]);
 const expenseDialog=dialogs.at(-1);expenseDialog.values.expense_name='EXPENSE-1';expenseDialog.values.approver='manager@example.com';
 pos.call = async (method, params) => {assert.equal(method,'request_shift_expense_approval_code');assert.equal(params.expense_name,'EXPENSE-1');assert.equal(params.approver,'manager@example.com');return {name:'EXPENSE-APPROVAL-1'};};
 await expenseDialog.handlers['[data-fieldname="expense_name"] input, [data-fieldname="approver"] select']();
 let resolvePermissions, reads = 0, renders = 0, headerRenders = 0;
 pos.state = {permissions: {can_void_items: false}};
 pos.renderHeaderActions = () => {headerRenders++;};
 pos.renderFields = pos.renderCart = () => {renders++;};
 pos.call = async method => {assert.equal(method, 'get_pos_permissions');reads++;return new Promise(resolve => {resolvePermissions = resolve;});};
 const first = pos.refreshPosPermissions(), second = pos.refreshPosPermissions();
 assert.equal(reads, 1, 'concurrent permission updates share a request');
 resolvePermissions({can_void_items: true, can_void_waste: false, can_request_returns: true, can_return_waste: false});
 await Promise.all([first, second]);
 assert.equal(pos.state.permissions.can_void_items, true);assert.equal(renders, 2);assert.equal(headerRenders, 1, "refresh header and menu permissions live");
 console.log('PASS: live permissions, direct actions, password/OTP requests, failed approval recovery, comments and cancellation.');
}
run().catch(error => {console.error(error);process.exitCode = 1;});
