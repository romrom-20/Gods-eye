const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../../godseye/static/app.js'), 'utf8');
const controller = source.slice(source.indexOf('// Local checkpoint import:'), source.indexOf('// End local checkpoint import.'));
const refresh = source.slice(source.indexOf('async function refresh('), source.indexOf('// Local checkpoint import:'));
const sidebar = source.slice(source.indexOf('function sidebarCheckpoints()'), source.indexOf('async function refresh('));
const options = source.slice(source.indexOf('function option('), source.indexOf('function drawArchitecture()'));
const roots = [{id:'paper',name:'Original policy',parent:null},{id:'zero',name:'Zero initialization',parent:null}];
const live = {mode:'local',backend:'minatar-breakout-v1',capabilities:['checkpoint_import'],checkpoints:roots};
const record = {id:'imported-root',name:'Imported weights',parent:null,sha256:'a'.repeat(64),source_sha256:'b'.repeat(64),provenance:'Local MIT weights',created:'now',backend:live.backend};
const event = {preventDefault(){}};
function setup(responses = [], config = live, recorded = false) {
  const nodes = {}, calls = [], reads = [], tensors = [];
  function node() {return {hidden:false,disabled:false,value:'',textContent:'',files:[],attrs:{},children:[],listeners:{},
    classList:{toggle(){}},setAttribute(k,v){this.attrs[k]=v;},getAttribute(k){return this.attrs[k]??null;},removeAttribute(k){delete this.attrs[k];},focus(){this.focused=true;},
    addEventListener(k,f){this.listeners[k]=f;},replaceChildren(){this.children=[];},append(...v){this.children.push(...v);},
    set innerHTML(v){throw Error('Untrusted HTML write: '+v);}};}
  const $ = id => nodes[id] ||= node();
  const ctx = {$,staticDemo:recorded,state:{checkpoints:config.checkpoints,mode:config.mode},Uint8Array,
    btoa:s=>Buffer.from(s,'binary').toString('base64'),
    message(id,text,error){$(id).textContent=text;$(id).error=error;},showView(v){ctx.state.view=v;},
    shortLabel(id){return ctx.state.checkpoints.find(c=>c.id===id)?.name||id;},fmt:String,
    document:{createElement:node},window:{scrollTo(){}},configureMode(){},renderExperimentBoard(){},
    async loadTensor(){tensors.push($('inspect-model').value);},
    async api(path,body){calls.push({path,body});const response=responses.shift();if(response instanceof Error)throw response;return typeof response==='function'?response():response;},
  };
  vm.createContext(ctx);
  vm.runInContext(options+sidebar+refresh+controller+'\nglobalThis.importState=checkpointImport;',ctx);
  ctx.configureImport(config);
  $('import-name').value = 'Imported weights';
  $('import-provenance').value = 'Local MIT weights';
  $('import-file').files = [{name:'policy.npz',size:3,async arrayBuffer(){reads.push(true);return new Uint8Array([80,75,3]).buffer;}}];
  return {...ctx,nodes,calls,reads,tensors,$};
}
test('import is discoverable but unsupported or recorded states cannot read files or POST',async()=>{
  for(const config of [{...live,capabilities:[]},{...live,capabilities:undefined},{...live,mode:'recorded-demo'},{...live,backend:'other'}]) {
    const x=setup([],config);await x.submitImport(event);x.openImport();
    assert.equal(x.calls.length,0);assert.equal(x.reads.length,0);assert.equal(x.$('import-open').disabled,true);
    assert.match(x.$('import-support').textContent,/unsupported|read-only/);
  }
  const x=setup([],live,true);await x.submitImport(event);assert.equal(x.calls.length,0);assert.equal(x.$('import-open').hidden,true);assert.equal(x.$('import-sidebar').hidden,true);
});
test('open form moves to workbench and focuses the file picker without importing',()=>{
  const x=setup();x.openImport();assert.equal(x.state.view,'workbench');assert.equal(x.$('import-file').focused,true);assert.equal(x.$('import-form').hidden,false);assert.equal(x.calls.length,0);
});
for(const [name,size] of [['weights.pkl',3],['weights.npz',0],['weights.npz',131073]])test('invalid/oversize file rejected before read: '+name+' '+size,async()=>{
  const x=setup();Object.assign(x.$('import-file').files[0],{name,size});await x.submitImport(event);
  assert.equal(x.reads.length,0);assert.equal(x.calls.length,0);assert.equal(x.$('import-file').focused,true);assert.equal(x.$('import-file').attrs['aria-invalid'],'true');
});
test('required name and bounded source notes focus errors before reading',async()=>{
  const x=setup();x.$('import-name').value='   ';await x.submitImport(event);assert.equal(x.$('import-name').focused,true);
  x.$('import-name').value='a'.repeat(81);await x.submitImport(event);assert.equal(x.reads.length,0);
  x.$('import-name').value='Valid';x.$('import-provenance').value='x'.repeat(2001);await x.submitImport(event);assert.equal(x.$('import-provenance').focused,true);assert.equal(x.calls.length,0);
});
test('explicit success posts exact bounded payload, refreshes, selects root, preserves bundled choices, compares without execution',async()=>{
  const x=setup([record,{...live,checkpoints:[...roots,record]}]);await x.submitImport(event);
  assert.deepEqual(JSON.parse(JSON.stringify(x.calls[0])),{path:'/api/v1/checkpoints/import',body:{name:'Imported weights',provenance:'Local MIT weights',npz_base64:'UEsD'}});
  assert.deepEqual(x.calls.map(c=>c.path),['/api/v1/checkpoints/import','/api/v1/state']);
  for(const id of ['inspect-model','patch-base','base'])assert.equal(x.$(id).value,record.id);
  for(const id of ['inspect-model','patch-base','base','candidate'])assert.deepEqual(x.$(id).children.map(c=>c.value),['paper','zero',record.id]);
  assert.equal(x.$('import-submit').disabled,true);assert.match(x.$('import-status').textContent,/No AI run started/);
  assert.match(x.$('import-metadata').textContent,/Imported original.*\nSource file SHA256: b{64}/);
  assert.equal(x.$('checkpoint-list').children.length,3);assert.equal(x.$('checkpoint-list').children[2].children[0].textContent,'◇');
  x.$('import-compare').onclick();assert.equal(x.state.view,'evaluate');assert.equal(x.$('base').value,record.id);assert.equal(x.$('candidate').value,'paper');assert.equal(x.calls.length,2);
});
test('duplicate click during file read or POST issues exactly one write',async()=>{
  let release;const x=setup([()=>new Promise(resolve=>{release=()=>resolve(record);}),{...live,checkpoints:[...roots,record]}]);
  const first=x.submitImport(event);await x.submitImport(event);await Promise.resolve();assert.equal(x.calls.length,1);assert.equal(x.$('import-submit').disabled,true);release();await first;assert.equal(x.calls.filter(c=>c.body).length,1);
});
test('authoritative rejection is safely shown, retains form and allows an explicit corrected submission',async()=>{
  const error=Object.assign(Error('Only float32 W1/W2/W3 tensors accepted.'),{status:422});const x=setup([error]);await x.submitImport(event);
  assert.match(x.$('import-status').textContent,/server: Only float32/);assert.equal(x.$('import-name').value,'Imported weights');assert.equal(x.$('import-submit').disabled,false);assert.equal(x.calls.length,1);
});
for(const failure of [Error('Disconnected'),Object.assign(Error('Server failure'),{status:500}),{parent:'bad'},null])test('uncertain POST never retries and requires explicit refresh even after edits',async()=>{
  const x=setup([failure,live]);await x.submitImport(event);
  assert.match(x.$('import-status').textContent,/outcome is unknown/);assert.equal(x.$('import-submit').disabled,true);assert.equal(x.$('import-status').focused,true);
  x.$('import-name').listeners.input();await x.submitImport(event);assert.equal(x.calls.length,1);assert.equal(x.$('import-file').files[0].name,'policy.npz');
  await x.$('import-refresh').onclick();assert.deepEqual(x.calls.map(c=>c.path),['/api/v1/checkpoints/import','/api/v1/state']);assert.equal(x.importState.uncertain,false);assert.equal(x.$('import-submit').disabled,false);
});
test('acknowledged import with failed refresh never reposts and reconciles selection',async()=>{
  const x=setup([record,Error('refresh down'),{...live,checkpoints:[...roots,record]}]);await x.submitImport(event);
  assert.match(x.$('import-status').textContent,/Import acknowledged/);assert.equal(x.$('import-submit').disabled,true);
  await x.submitImport(event);assert.equal(x.calls.length,2);await x.$('import-refresh').onclick();assert.equal(x.$('inspect-model').value,record.id);assert.equal(x.calls.filter(c=>c.body).length,1);
});
test('imported roots without patch/diff and user source markup render only as inert text',()=>{
  const injection='<img src=x onerror="globalThis.pwned=true">';
  const root={...record,name:injection,provenance:injection};const x=setup([],{...live,checkpoints:[...roots,root]});
  x.$('inspect-model').value=root.id;x.renderImportMetadata();x.sidebarCheckpoints();
  assert.ok(x.$('import-metadata').textContent.includes(injection));assert.match(x.$('import-metadata').textContent,/user-provided, unverified/);
  assert.equal(x.$('checkpoint-list').children[2].children[1].textContent,injection);assert.equal(x.pwned,undefined);
  x.$('inspect-model').value='paper';x.renderImportMetadata();assert.equal(x.$('import-metadata').hidden,true);assert.equal(x.$('import-metadata').textContent,'');
});
test('import uses the existing authenticated API helper and propagates known rejection status',async()=>{
  const calls=[];const ctx={document:{documentElement:{dataset:{}}},state:{token:'session-token'},fetch:async(path,options)=>{calls.push({path,options});return {ok:false,status:422,json:async()=>({error:'Invalid NPZ'})};}};
  vm.createContext(ctx);vm.runInContext(source.slice(source.indexOf('let demoPayload;'),source.indexOf('function configureMode(')),ctx);
  await assert.rejects(ctx.api('/api/v1/checkpoints/import',{name:'test',provenance:'',npz_base64:'UEsD'}),e=>e.status===422&&e.message==='Invalid NPZ');
  assert.equal(calls[0].options.headers.Authorization,'Bearer session-token');assert.equal(calls[0].options.method,'POST');
});
test('file read failure keeps the draft and cannot send a write',async()=>{
  const x=setup();x.$('import-file').files[0].arrayBuffer=async()=>{throw Error('local read denied');};
  await x.submitImport(event);assert.equal(x.calls.length,0);assert.match(x.$('import-status').textContent,/Could not read/);assert.equal(x.$('import-name').value,'Imported weights');assert.equal(x.$('import-submit').disabled,false);
});
test('failed reconciliation retains uncertain lock and never posts again',async()=>{
  const x=setup([Error('lost'),Error('offline')]);await x.submitImport(event);await x.$('import-refresh').onclick();
  assert.equal(x.importState.uncertain,true);assert.equal(x.$('import-submit').disabled,true);assert.match(x.$('import-status').textContent,/form is preserved/);assert.equal(x.calls.filter(c=>c.body).length,1);
});
test('exact 128 KiB boundary is read and encoded once; importer unlocks its action after success',async()=>{
  const x=setup([record,{...live,checkpoints:[...roots,record]}]);x.$('import-file').files=[{name:'UPPER.NPZ',size:131072,async arrayBuffer(){return new Uint8Array(131072).buffer;}}];
  await x.submitImport(event);assert.equal(x.calls[0].body.npz_base64.length,174764);assert.equal(x.$('import-open').disabled,false);assert.equal(x.$('import-sidebar').disabled,false);
});
