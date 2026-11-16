const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
let config, dialog, input = '';
const context = {frappe:{pages:{'point-of-sale':{}},ui:{Dialog:class {
 constructor(options) {config=options;dialog=this;}
 get_value() {return input;} show() {} hide() {this.hidden=true;}
 disable_primary_action() {this.disabled=true;} enable_primary_action() {this.disabled=false;}
}}},__:value=>value};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'point_of_sale.js'),'utf8')+'\nglobalThis.POS=RMSPointOfSale;',context);
function create(name='ORDER-1') {
 const pos=Object.create(context.POS.prototype);
 pos.state={order_name:name,order_status:name?'Confirmed':'Open',order_notes:'Original',cart:[]};
 pos.orderModified='v1'; pos.syncedOrderMeta={order_notes:'Original'};
 pos.ensureCurrentOrderActive=async()=>true;
 pos.flushDraftSave=async()=>{};pos.renderCart=()=>{};pos.saveDraft=()=>{pos.pendingSave=true;};
 pos.showError=error=>{pos.error=error;};
 pos.calls=[];
 pos.call=async(method,args)=>{pos.calls.push({method,args});return {name:args.order_name,order_notes:args.notes,modified:'v2'};};
 return pos;
}
(async()=>{
 const pos=create(); pos.editOrderNotes(); input='  تجهيز الطلب الساعة ٣  ';
 await config.primary_action();
 assert.equal(pos.state.order_notes,'تجهيز الطلب الساعة ٣');
 assert.equal(pos.calls[0].args.expected_modified,'v1');
 assert.equal(pos.syncedOrderMeta.order_notes,pos.state.order_notes);
 assert.equal(pos.orderModified,'v2');assert.equal(dialog.hidden,true);
 assert.equal(pos.orderPayload().order_notes,pos.state.order_notes);
 pos.editOrderNotes();input='';await config.primary_action();assert.equal(pos.state.order_notes,'');
 const fresh=create(null);fresh.editOrderNotes();input='Pack separately';await config.primary_action();
 assert.equal(fresh.state.order_notes,'Pack separately');assert.equal(fresh.calls.length,0);assert.equal(fresh.pendingSave,true);
 const failed=create();failed.call=async()=>{throw Error('Offline');};failed.editOrderNotes();input='Changed';await config.primary_action();
 assert.equal(failed.state.order_notes,'Original','failed requests keep the saved comment');assert.equal(dialog.hidden,undefined);
 const stale=create();let resume;stale.flushDraftSave=()=>new Promise(resolve=>{resume=resolve;});
 stale.editOrderNotes();input='Old order note';const action=config.primary_action();for(let tick=0;!resume && tick<5;tick++) await Promise.resolve();assert.equal(typeof resume,'function');stale.saleRevision=1;resume();await action;
 assert.equal(stale.calls.length,0,'a note from a previous sale cannot be attached to a new one');
 console.log('PASS: whole-order comments save, clear, survive draft payloads, preserve failed edits and reject stale-sale callbacks.');
})().catch(error=>{console.error(error);process.exitCode=1;});
