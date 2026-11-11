const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname,'../../godseye/static/app.js'),'utf8');
const download = source.slice(source.indexOf('  // Explicit checkpoint download:'), source.indexOf('  // Activity is an optional'));
const activity = source.slice(source.indexOf('  // Activity is an optional'),source.indexOf('  function bound(v)'));
function setup(responses=[]) {
  const nodes={}, calls=[], downloads=[], revoked=[];
  const $=id=>nodes[id] ||= {hidden:false,disabled:false,textContent:'',children:[],replaceChildren(){this.children=[];},append(x){this.children.push(x);},get firstElementChild(){const self=this;return {remove(){self.children.shift();}};}};
  const ctx={$,state:{token:'session-auth'},run:{experiment_id:'run',spec_hash:'a'.repeat(64),status:'running'},epoch:0,AbortController,
    setTimeout(){return 1;},clearTimeout(){},URL:{createObjectURL(){return 'blob:test';},revokeObjectURL(x){revoked.push(x);}},
    document:{body:{append(){}},createElement(){return {textContent:'',click(){downloads.push({href:this.href,download:this.download});},remove(){}};}},
    valid(kind,v){if(kind!=='error_response'||!v.error)throw Error('invalid');return v;},parseResponse:JSON.parse,
    async fetch(url,opts){calls.push({url,opts});const r=responses.shift();if(r instanceof Error)throw r;return typeof r==='function'?r():r;},
  };
  vm.createContext(ctx);
  vm.runInContext(download+activity+`\nglobalThis.api={downloadCheckpoint,observeActivity,activityLabel,setTarget:v=>downloadTarget=v,getCursor:()=>activityCursor,getFence:()=>activityFence};`,ctx);
  return {...ctx,...ctx.api,nodes,calls,downloads,revoked};
}
const target={schema_version:1,experiment_id:'run',artifact_id:'manifest'};
const ok={ok:true,headers:{get:()=> 'application/json'},blob:async()=>({fixture:true})};
test('checkpoint requires a validated completed result target and an explicit click',async()=>{
  const x=setup([ok]);await x.downloadCheckpoint();assert.equal(x.calls.length,0);
  x.setTarget(target);assert.equal(x.calls.length,0);await x.downloadCheckpoint();
  assert.equal(x.calls[0].url,'/api/v1/experiments/export');
  assert.deepEqual(JSON.parse(x.calls[0].opts.body),target);
  assert.equal(x.calls[0].opts.headers.Authorization,'Bearer session-auth');
  assert.deepEqual(x.downloads,[{href:'blob:test',download:'godseye-checkpoint-run.json'}]);
  assert.deepEqual(x.revoked,['blob:test']);assert.equal(x.nodes['goal-download'].disabled,false);
});
test('duplicate in-flight download clicks issue one request',async()=>{
  let release;const x=setup([()=>new Promise(resolve=>{release=()=>resolve(ok);})]);x.setTarget(target);
  const first=x.downloadCheckpoint();await x.downloadCheckpoint();assert.equal(x.calls.length,1);
  assert.equal(x.nodes['goal-download'].disabled,true);release();await first;
});
for(const error of [new Error('private network marker'),{ok:false,text:async()=>JSON.stringify({error:{message:'Experiment is unavailable in this scope.'}})},{ok:true,headers:{get:()=> 'text/html'}}]) {
  test('download errors are actionable, bounded, and never automatically retried',async()=>{
    const x=setup([error]);x.setTarget(target);await x.downloadCheckpoint();
    assert.equal(x.calls.length,1);assert.equal(x.downloads.length,0);
    assert.match(x.nodes['goal-download-status'].textContent,/retry.*explicitly/i);
    assert.doesNotMatch(x.nodes['goal-download-status'].textContent,/private network/);
    assert.equal(x.nodes['goal-download'].disabled,false);
  });
}
function page(events,after=0,high=events.length){return {schema_version:1,experiment_id:'run',spec_hash:'a'.repeat(64),available:true,status:'running',phase:{name:'unknown',event_sequence:high||null},events,next_cursor:events.at(-1)?.sequence??after,high_water:high,gap:false,has_more:(events.at(-1)?.sequence??after)<high};}
const event=(sequence,kind='activity_finished')=>({sequence,kind,operation:'read',arm:'agent',count:null});
const response=v=>({ok:true,text:async()=>JSON.stringify(v)});
test('activity pages keep cursor fences, reject replay/gaps and reconnect without launching',async()=>{
  const x=setup([response(page([event(1)])),new Error('disconnected'),response(page([event(1)])),response(page([event(2)],1,2))]);
  await x.observeActivity();assert.equal(x.getCursor(),1);assert.equal(x.nodes['goal-activity-events'].children.length,1);
  await x.observeActivity();assert.equal(x.getCursor(),1);assert.match(x.nodes['goal-phase'].textContent,/unavailable/);
  await x.observeActivity();assert.equal(x.getCursor(),1);assert.equal(x.nodes['goal-activity-events'].children.length,1);
  await x.observeActivity();assert.equal(x.getCursor(),2);assert.equal(x.nodes['goal-activity-events'].children.length,2);
  assert.ok(x.calls.every(c=>c.url.endsWith('/activity')));
});
test('a fenced durable gap stays visible when later contiguous history recovers',async()=>{
  const gap={...page([],0,3),available:false,gap:true,next_cursor:3,has_more:false};
  const x=setup([response(gap),response(page([event(4)],3,4))]);
  await x.observeActivity();assert.equal(x.getCursor(),3);assert.match(x.nodes['goal-activity-notice'].textContent,/unavailable/);
  await x.observeActivity();assert.equal(x.getCursor(),4);assert.match(x.nodes['goal-activity-notice'].textContent,/earlier observations are missing/);
});
test('unknown event names and raw labels cannot become public DOM content',async()=>{
  const x=setup([response(page([{...event(1),kind:'PRIVATE PROVIDER TEXT'}]))]);
  await x.observeActivity();assert.equal(x.nodes['goal-activity-events'].children.length,0);
  assert.match(x.nodes['goal-activity-notice'].textContent,/unavailable/);
});
test('static and mock controllers return before installing download or activity handlers',()=>{
  const closure=source.slice(source.indexOf('// Live goal transport.'));
  for(const recorded of [false,true]) {
    const ctx={staticDemo:recorded,location:{search:recorded?'':'?goalMode=mock'},URLSearchParams,initialize(){},$(){throw Error('DOM accessed');},fetch(){throw Error('network');}};
    vm.runInNewContext(closure,ctx);
  }
});
