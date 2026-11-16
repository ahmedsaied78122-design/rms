const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = {frappe:{pages:{'point-of-sale':{}}},__:s=>s,clearTimeout};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'point_of_sale.js'),'utf8')+'\nglobalThis.POS=RMSPointOfSale;',context);
function register() {
 const p=Object.create(context.POS.prototype);
 p.state={store:'Maadi',brand:'East',order_type:'Takeaway',category:null,search:'',products:[],categories:[{name:'A'},{name:'B'}]};
 p.page={main:{}};p.catalogRequestId=0;p.renders=[];p.errors=[];
 p.renderProducts=()=>p.renders.push({loading:p.state.catalog_loading,products:p.state.products,category:p.state.category});
 p.renderCategories=()=>{};p.showError=e=>p.errors.push(e);
 return p;
}
(async()=>{
 const p=register(), calls=[];let finish;
 const all=Array.from({length:251},(_,i)=>({name:'P'+i,title:'Product '+i,product_category:i===250?'B':'A',price:25}));
 p.call=(method,args)=>{calls.push({method,args});return new Promise(resolve=>{finish=resolve;});};
 const initial=p.loadCatalog(), next=p.selectCategory('B');
 assert.equal(calls.length,1,'initial load and drilldown share a pending snapshot');
 assert.equal(calls[0].args.full_menu,1);assert.equal(calls[0].args.category,null);
 finish(all);await Promise.all([initial,next]);
 assert.equal(p.state.category,'B');assert.equal(p.state.products.length,251,'the menu includes products beyond the old 200-row limit');
 p.renders=[];
 for(let i=0;i<30;i++) await p.selectCategory(i%2?'A':'B');
 assert.equal(calls.length,1,'category navigation never calls the server while the snapshot is fresh');
 assert(p.renders.every(r=>!r.loading),'no loading state during warm navigation');
 assert(p.renders.every(r=>r.products===all));

 p.menuSnapshot.refreshAt=0;let refreshFinish;
 p.call=()=>{calls.push('refresh');return new Promise(resolve=>{refreshFinish=resolve;});};
 const refresh=p.selectCategory('B'), refreshAgain=p.selectCategory('A');
 assert.equal(calls.length,2,'stale navigation starts just one refresh');
 assert.equal(p.state.products,all);assert.equal(p.state.catalog_loading,false,'refresh keeps the menu usable');
 const changed=[{name:'New',product_category:'A',price:39}];refreshFinish(changed);
 await Promise.all([refresh,refreshAgain]);assert.equal(p.state.products,changed);

 // A search uses server barcode matching, and a late snapshot cannot replace it.
 p.menuSnapshot.refreshAt=0;
 let completeSnapshot,completeSearch;
 p.call=(method,args)=>new Promise(resolve=>{if(args.search)completeSearch=resolve;else completeSnapshot=resolve;});
 const staleRefresh=p.loadCatalog();p.state.search='01234';const search=p.loadCatalog();
 const matches=[{name:'Barcode',barcode_match:true,price:29}];completeSearch(matches);await search;
 completeSnapshot(all);await staleRefresh;assert.equal(p.state.products,matches);
 p.state.search='';await p.loadCatalog();assert.equal(p.state.products,all,'clearing search instantly restores the full menu');

 // Prices and availability must never cross Store, Brand or Order Type contexts.
 for (const field of ['store','brand','order_type']) {
  const q=register();let resolveOld,resolveNew;
  q.call=()=>new Promise(resolve=>{if(!resolveOld)resolveOld=resolve;else resolveNew=resolve;});
  const old=q.loadCatalog();q.state[field]='Other';const fresh=q.loadCatalog();
  assert.equal(q.state.products.length,0,'old context products are cleared immediately');
  const current=[{name:'New scope',price:77}];resolveNew(current);await fresh;resolveOld(all);await old;
  assert.equal(q.state.products,current);assert(q.menuSnapshot.key.includes('Other'));
 }
 const q=register();let resolvePending;q.call=()=>new Promise(resolve=>{resolvePending=resolve;});
 const pending=q.loadCatalog();q.state.store=null;await q.loadCatalog();resolvePending(all);await pending;
 assert.equal(q.state.products.length,0,'a response cannot restore a cleared branch');

 const failure=register();failure.call=async()=>all;await failure.loadCatalog();failure.menuSnapshot.refreshAt=0;
 failure.call=async()=>{throw Error('offline');};await failure.loadCatalog();assert.equal(failure.state.products,all);assert.equal(failure.errors.length,0,'background network errors retain the cached menu');
 failure.menuSnapshot.refreshAt=0;failure.call=async()=>{throw {responseJSON:{exc_type:'PermissionError'}};};
 await failure.loadCatalog();assert.equal(failure.state.products.length,0);assert.equal(failure.errors.length,1,'access denial drops the cached menu');
 // An idle, visible register refreshes stale data without a loading interruption.
 let tick;
 context.window={setInterval:fn=>{tick=fn;return 1;},addEventListener(){}};
 context.document={visibilityState:'visible',body:{classList:{contains:()=>true}}};
 const periodic=register();let periodicCalls=0;
 periodic.call=async()=>{periodicCalls++;return all;};periodic.refreshPosPermissions=()=>{};
 await periodic.loadCatalog();periodic.startOrderSync();tick();assert.equal(periodicCalls,1);
 periodic.menuSnapshot.refreshAt=0;tick();assert.equal(periodicCalls,2);assert.equal(periodic.state.catalog_loading,false);
 await new Promise(resolve=>setImmediate(resolve));tick();assert.equal(periodicCalls,2);
 console.log('PASS: instant category navigation; 251 products; request coalescing; background refresh; barcode races; Store/Brand/Order Type isolation; access revocation.');
})().catch(e=>{console.error(e);process.exitCode=1;});
