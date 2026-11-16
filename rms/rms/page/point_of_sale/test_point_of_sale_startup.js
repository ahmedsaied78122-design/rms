const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const context = {frappe:{pages:{'point-of-sale':{}},session:{user:'cashier@example.com'},show_alert(){}},__:text=>text,console,clearTimeout};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'point_of_sale.js'),'utf8')+'\nglobalThis.POS=RMSPointOfSale;',context);
function register(){
 const pos=Object.create(context.POS.prototype);
 pos.state={cart:[],stores:[],brands:[],order_types:[],permissions:{},category:null,search:''};
 pos.render=pos.renderCart=pos.rememberOrderSnapshot=()=>{};
 pos.showError=error=>{throw error;};pos.loadContextDetails=async()=>{pos.state.payment_config=[{mode_of_payment:'Cash'}];};
 pos.showPaymentScreen=()=>{pos.paymentShown=true;};pos.catalogRequestId=0;
 return pos;
}
async function run(){
 const pos=register(),calls=[];
 pos.pendingResumeContext={store:'STORE-1',order_name:'ORDER-9',session:'SESSION-1',screen:'payment'};
 const order={name:'ORDER-9',store:'STORE-1',status:'Confirmed',cashier_session:'SESSION-1',restaurant_brand:'BRAND-1',order_type:'Takeaway',items:[],grand_total:110};
 let finishCatalog;
 pos.call=async method=>{
  calls.push(method);
  if(method==='get_bootstrap')return {store:{name:'STORE-1'},brands:[{name:'BRAND-1'}],order_types:[{name:'Takeaway'}],session:{name:'SESSION-1'},permissions:{can_checkout:true}};
  if(method==='get_order')return order;
  if(method==='get_guest_checks')return {guest_checks:[]};
  throw Error('Unexpected startup request '+method);
 };
 pos.loadCatalog=()=>{calls.push('get_catalog');return new Promise(resolve=>{finishCatalog=resolve;});};
 await pos.loadBootstrap('STORE-1');
 assert.equal(pos.paymentShown,true,'payment must restore while menu is still pending');
 assert.equal(pos.state.bootstrap_loading,false);assert.equal(pos.state.order_name,'ORDER-9');
 assert.equal(calls.filter(method=>method==='get_order').length,1,'saved order fetched once');
 assert.equal(calls.filter(method=>method==='get_catalog').length,1,'only one background menu fetch');
 assert.ok(!calls.includes('get_order_state'),'full order snapshot already carries current status');
 finishCatalog([]);
 const fresh=register();let finishContext,startedMenu=false;
 fresh.call=async()=>({store:{name:'STORE-1'},brands:[{name:'BRAND-1'}],order_types:[{name:'Takeaway'}],session:null,permissions:{}});
 fresh.loadContextDetails=()=>new Promise(resolve=>{finishContext=resolve;});
 fresh.loadCatalog=async()=>{startedMenu=true;return [];};
 const opening=fresh.loadBootstrap();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(startedMenu,true,'new-sale catalog starts alongside context data');
 finishContext();await opening;
 console.log('PASS: payment restores without waiting for menu; one order snapshot; one catalog request; parallel new-sale startup.');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
