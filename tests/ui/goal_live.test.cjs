const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname,'../../godseye/static/app.js'),'utf8');
const schema = source.slice(source.indexOf('const experimentContract ='),source.indexOf('// Live goal transport.'));
const validation = source.slice(source.indexOf('  const canonical ='),source.indexOf('  function save()'));
const restore = source.slice(source.indexOf('      const p = saved.pending;'),source.indexOf('      if (saved.run)'));
const recovery = source.slice(source.indexOf('  async function reconcile(action'),source.indexOf('  async function perform(fn)'));
const transport = source.slice(source.indexOf('  function parseResponse(raw)'),source.indexOf('  function render(v)'));
function setup(responses) {
  const calls = [], delays = [], savedSnapshots = [], pending = {baseline_id:'baseline',spec_hash:'a'.repeat(64),body:{schema_version:1,confirmed:true,draft_id:'expired',idempotency_key:'original',spec_hash:'a'.repeat(64)},uncertain:false}, Ctx = {
    pending, run:null, busy:false, invalidations:0,
    $() { return {}; }, invalidate() { Ctx.invalidations++; },
    bound(v) { return v; }, async observe() {},
    epoch:0, state:{token:''}, AbortController, TextEncoder,
    setTimeout(fn,ms) { if (ms !== 15000) {delays.push(ms); queueMicrotask(fn);} return 1; },
    clearTimeout() {}, save() { savedSnapshots.push(JSON.parse(JSON.stringify(Ctx.pending))); return true; }, say() {},
    async fetch(url,opts) { calls.push({url,body:opts.body}); const r = responses.shift(); if (r instanceof Error) throw r; return {ok:r.ok,status:r.status,text:async()=>r.raw ?? JSON.stringify(r.body)}; },
  };
  vm.createContext(Ctx);
  vm.runInContext(schema+'\nconst C = experimentContract;\n'+validation+transport+recovery+'\nfunction restorePending(saved) {'+restore+'}\nglobalThis.testApi={valid,shape,canonical,request,reconcile,reviewAgain,restorePending,getPending:()=>pending,getInvalidations:()=>invalidations,C};',Ctx);
  return {...Ctx.testApi,calls,delays,savedSnapshots};
}
function error(code) {
  const {C} = setup([]);
  return {ok:false,status:({spec_conflict:409,queue_full:503,worker_unavailable:503,rate_limited:429})[code],body:{schema_version:1,error:{code,field:'$',message:C.messages[code]},retry:C.retries[code]}};
}
const start = {ok:true,body:{schema_version:1,experiment_id:'run',spec_hash:'a'.repeat(64),status:'queued'}};
test('same request retries share a three-attempt budget across transient codes',async()=>{
  const x = setup(['queue_full','rate_limited','worker_unavailable','queue_full'].map(error));
  await assert.rejects(x.request('start',{confirmed:true}),/queue_full/);
  assert.equal(x.calls.length,4); assert.deepEqual(x.delays,[5000,10000,20000]);
  assert.ok(x.calls.every(c=>c.body===x.calls[0].body));
});
test('successful retry retains exact body and stops',async()=>{
  const x = setup([error('rate_limited'),start]);
  const v = await x.request('start',{draft_id:'draft',idempotency_key:'original'});
  assert.equal(v.experiment_id,'run'); assert.equal(x.calls.length,2);
  assert.equal(x.calls[0].body,x.calls[1].body);
});
for (const [label,response] of [['network',new Error('disconnect')],['unavailable',error('unavailable')],['malformed',{ok:false,body:{error:'raw private message'}}],['wrong guidance',{ok:false,body:{...error('queue_full').body,retry:{action:'same_request',after_seconds:1,max_attempts:3}}}]]) {
  test(`${label} never retries an uncertain mutation`,async()=>{
    const x=setup([response]); await assert.rejects(x.request('start',{idempotency_key:'original'}));
    assert.equal(x.calls.length,1); assert.deepEqual(x.delays,[]);
  });
}
test('reload and manual reconciliation disable automatic retries',async()=>{
  const x=setup([error('queue_full')]); await assert.rejects(x.request('start',{}, {noAuto:true,retries:0}));
  assert.equal(x.calls.length,1);
});
test('unknown version, extra fields and malformed response fail closed',()=>{
  const {valid}=setup([]);
  for (const change of [{schema_version:2},{status:'ready'},{extra:'secret'},{spec_hash:null}]) assert.throws(()=>valid('start_response',{...start.body,...change}));
});
test('phase and evidence cannot fabricate completed measurements',()=>{
  const {valid}=setup([]);
  const status={schema_version:1,experiment_id:'run',spec_hash:'a'.repeat(64),status:'completed',phase:{name:'unknown',event_sequence:null},verdict:'no_improvement',reason:null,usage:{requests:1,input_tokens:0,output_tokens:0,tool_calls:0,elapsed_seconds:1,usage_complete:false,request_in_flight:true}};
  assert.throws(()=>valid('results_response',{...status,evidence:null}));
  assert.throws(()=>valid('status_response',{...status,phase:{name:'testing',event_sequence:1}}));
  assert.throws(()=>valid('status_response',{...status,status:'running',verdict:'improved'}));
  assert.equal(valid('status_response',status).usage.usage_complete,false);
});

test('duplicate JSON keys fail closed before interpreting a response',async()=>{
  const x=setup([{ok:true,raw:'{"schema_version":1,"schema_version":1}'}]);
  await assert.rejects(x.request('start',{}),/invalid/);
  assert.equal(x.calls.length,1);
});

test('expired plan permits explicit review again without launching or clearing the tuple early',async()=>{
  const x=setup([error('spec_conflict')]);
  const tuple=JSON.stringify(x.getPending().body);
  await assert.rejects(x.reconcile(),/spec_conflict/);
  assert.equal(x.getPending().rejected,true);
  assert.equal(x.savedSnapshots[0].inFlight,true,'persist uncertainty before dispatch');
  assert.equal(x.savedSnapshots[1].inFlight,false);
  assert.equal(x.savedSnapshots[1].rejected,true);
  assert.equal(JSON.stringify(x.getPending().body),tuple);
  assert.equal(x.getInvalidations(),0);
  x.reviewAgain();
  assert.equal(x.getPending(),null);
  assert.equal(x.getInvalidations(),1);
  assert.equal(x.calls.length,1);
});
for (const response of [new Error('lost response'),error('unavailable'),{ok:false,raw:'not JSON'}, {...error('spec_conflict'),status:503}]) {
  test('uncertain admission prevents re-review even after a later plan rejection',async()=>{
    const x=setup([response,error('spec_conflict')]);
    const tuple=JSON.stringify(x.getPending().body);
    await assert.rejects(x.reconcile()); x.reviewAgain();
    assert.equal(JSON.stringify(x.getPending().body),tuple);
    await assert.rejects(x.reconcile(),/spec_conflict/); x.reviewAgain();
    assert.equal(x.getPending().rejected,false);
    assert.equal(JSON.stringify(x.getPending().body),tuple);
    assert.equal(x.getInvalidations(),0);
  });
}

test('reload during an in-flight start preserves uncertainty and the exact tuple',async()=>{
  const x=setup([error('spec_conflict')]);
  const p=JSON.parse(JSON.stringify(x.getPending())); p.inFlight=true;
  x.restorePending({pending:p});
  assert.equal(x.getPending().uncertain,true);
  await assert.rejects(x.reconcile(),/spec_conflict/); x.reviewAgain();
  assert.equal(JSON.stringify(x.getPending().body),JSON.stringify(p.body));
  assert.equal(x.getInvalidations(),0);
});
