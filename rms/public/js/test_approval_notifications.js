const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let clickHandler,requestArgs,lastDialog;
let response={name:'APPROVAL-1',action:'POS Order Discount',subject:'ORDER-1',store:'STORE-1',requester:'Administrator',requester_name:'Admin',created_at:'2026-11-05',expires_at:'2026-11-05',status:'Issued',remaining_seconds:120,code:'123456',historical_snapshot:true,payload:{discount_value:85,discount_type:'Percentage',discount_scope:'Net Total',currency:'EGP',total_before:228,total_after:34.2,payable_before:228,payable_after:34,discount_amount:170,taxes_before:28,taxes_after:4.2,comment:'<script>reason</script>',items:[]}};
const context={window:{},document:{addEventListener(type,handler,capture){assert.equal(type,'click');assert.equal(capture,true);clickHandler=handler;}},
 frappe:{utils:{escape_html:text=>String(text).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),copy_to_clipboard(){}},datetime:{str_to_user:value=>value},
  call:async args=>{requestArgs=args;return {message:response};},msgprint:error=>{throw Error(error);},ui:{Dialog:class{
   constructor(options){Object.assign(this,options);this.$wrapper={addClass(){},find(){const field={text(){return field;},prop(){return field;},attr(){return field;}};return field;},on(){}};lastDialog=this;}
   show(){this.visible=true;}hide(){this.visible=false;this.onhide?.();}
  }}},format_currency:(value,currency)=>Number(value).toFixed(2)+' '+currency,__:text=>text,Date,setInterval:()=>1,clearInterval(){}};
vm.createContext(context);vm.runInContext(fs.readFileSync(__dirname+'/approval_notifications.js','utf8'),context);
async function run(){
 let prevented=false,stopped=false,read=false;
 const link={dataset:{name:'NOTICE-1'},getAttribute:()=>'/app/approval-challenge/APPROVAL-1',classList:{remove:name=>{assert.equal(name,'unread');read=true;}}};
 clickHandler({target:{closest:selector=>selector==='.mark-as-read'?null:link},preventDefault(){prevented=true;},stopImmediatePropagation(){stopped=true;}});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(prevented,true);assert.equal(stopped,true);assert.equal(read,true);
 assert.equal(requestArgs.args.notification_name,'NOTICE-1');assert.equal(requestArgs.args.challenge_name,'APPROVAL-1');
 const html=lastDialog.fields[0].options;
 assert.doesNotMatch(html,/123456/);assert.match(html,/••••••/);assert.match(html,/data-approval-reveal/);assert.match(html,/data-approval-copy disabled/);assert.match(html,/85%/);assert.match(html,/228.00 EGP/);assert.match(html,/170.00 EGP/);assert.match(html,/34.00 EGP/);
 assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
 lastDialog.hide();response={...response,status:'Expired',code:null,remaining_seconds:0};
 await context.window.rmsShowApprovalPopup({challenge_name:'APPROVAL-1'});
 assert.ok(!lastDialog.fields[0].options.includes('data-approval-code'));
 console.log('PASS: approval notification opens private popup without navigation, money and code appear, notes escape and expired codes hide.');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
