const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {createHash}=require('node:crypto');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../godseye/static/app.js'),'utf8');
const controller=source.slice(source.indexOf('// Local Qwen workspace:'),source.indexOf('// End local Qwen controller.'));
const historical=JSON.parse(fs.readFileSync(path.join(__dirname,'../../experiments/local_lm_task_validation.json')));
const spec=historical.spec, sha=historical.spec_sha256;
const cap={schema_version:1,available:true,readonly:false,reason:null,model:spec.model,execution:'local_cpu',supported_goal:'correct_bounded_json',sample_request:'Improve JSON schema adherence',limits:{max_attempts:126,max_new_tokens:96,max_worker_seconds:1800,max_concurrency:1}};
const plan={schema_version:1,outcome:'ready',message:'SCRIPTED plan; no model execution',plan_id:'plan-scripted',expires_at:'2026-11-13T15:00:00Z',spec_sha256:sha,spec};
const job=(extra={})=>({id:'scripted-job',spec_sha256:sha,created_at:'2026-11-13T12:00:00Z',updated_at:'2026-11-13T12:00:01Z',status:'running',reason:null,phase:'development',progress:{reserved_attempts:1,finished_attempts:0,max_attempts:126},result_available:false,selected_delta_available:false,...extra});
const wrap=j=>({schema_version:1,job:j});
const response=(body,status=200)=>({ok:status<300,status,text:async()=>JSON.stringify(body)});
function setup(options={}) {
 const nodes=new Map(), calls=[], timers=new Map(), events={}, downloads=[], storage=options.storage||new Map(); let timerId=0;
 const el=(tag='div')=>({tag,value:'',checked:false,disabled:false,hidden:false,textContent:'',children:[],className:'',append(...xs){this.children.push(...xs);},replaceChildren(...xs){this.children=xs;},focus(){this.focused=true;},set innerHTML(v){throw Error('Unsafe HTML');}});
 const $=id=>{if(!nodes.has(id))nodes.set(id,el());return nodes.get(id);};
 $('lm-split').value='dev';
 const doc={hidden:false,createElement:el,addEventListener(name,fn){events[name]=fn;}};
 const queue=options.queue||[];
 const env={$,document:doc,staticMode:!!options.staticMode,token:()=>options.token||'',uuid:()=> '12345678-1234-4234-8234-123456789abc',
  storage:{getItem:k=>storage.get(k),setItem(k,v){if(options.storageFail)throw Error('blocked');storage.set(k,v);}},
  digest:async text=>createHash('sha256').update(text).digest('hex'),
  transport:async(url,opts)=>{calls.push({url,opts,body:opts.body&&JSON.parse(opts.body)}); const next=queue.shift(); if(next instanceof Error)throw next; if(typeof next==='function')return next(url,opts); if(!next)throw Error('Unexpected request '+url); return next;},
  clock:{setTimeout(fn,ms){timers.set(++timerId,{fn,ms});return timerId;},clearTimeout(id){timers.delete(id);}},download:(value,name)=>downloads.push({value,name})};
 const ctx={AbortController,console};vm.createContext(ctx);vm.runInContext(controller+'\nglobalThis.factory=createLmWorkspace;',ctx);
 const app=ctx.factory(env);
 return {$,nodes,queue,calls,timers,events,doc,downloads,storage,app,click:async id=>$(id).onclick?.(),
  async ready(){queue.push(response(cap),response({schema_version:1,jobs:[]}));await app.connect();},
  async review(){queue.push(response(plan));$('lm-request').value='Improve JSON schema adherence';await this.click('lm-plan');},
  async start(r=response(wrap(job()))){if(r)queue.push(r);$('lm-consent').checked=true;$('lm-consent').onchange();await this.click('lm-start');},
  async tick(){const t=[...timers.entries()].find(([,t])=>t.ms!==15000);assert.ok(t,'no poll timer');timers.delete(t[0]);await t[1].fn();return t[1].ms;},
 };
}
function result(j=job({status:'failed',reason:'budget_limited',phase:'finalizing',progress:{reserved_attempts:70,finished_attempts:70,max_attempts:126},result_available:true})) {
 return {schema_version:1,job:j,report:{spec_sha256:sha,status:'incomplete',verdict:'not_evaluated',development:historical.development,heldout:{},comparisons:{}},attempts:historical.attempts.map(a=>Object.fromEntries(['attempt_id','case_id','split','variant','status','output','input_tokens','output_tokens','elapsed_seconds'].map(k=>[k,a[k]]).concat([['spec_sha256',sha]]))),interrupted_attempts:0};
}
test('view, plan, sample and history never submit inference; exact fixed plan is reviewed',async()=>{
 const x=setup();await x.ready();await x.click('lm-sample');await x.review();
 assert.equal(x.$('lm-review').hidden,false);assert.equal(x.$('lm-review-title').focused,true);assert.equal(x.$('lm-start').disabled,true);
 assert.match(x.$('lm-spec').textContent,/3a49a9cd/);assert.ok(x.$('lm-review-facts').children.some(n=>n.textContent.includes('126 attempts')));
 assert.deepEqual(x.calls.map(c=>c.url),['/api/v1/lm/capabilities','/api/v1/lm/jobs','/api/v1/lm/plan']);
 x.$('lm-request').oninput();assert.equal(x.$('lm-review').hidden,true);
});
test('duplicate Start dispatches once and persists only original identities before network',async()=>{
 const x=setup({token:'memory-secret'});await x.ready();await x.review();let ack;
 const r=new Promise(resolve=>ack=resolve);
 const first=x.start(async()=>{const saved=[...x.storage.values()][0];assert.match(saved,/idempotency_key/);assert.ok(!saved.includes('Improve JSON')&&!saved.includes('memory-secret')&&!saved.includes('operations'));return r;});
 await x.click('lm-start');assert.equal(x.calls.filter(c=>c.url.endsWith('/jobs')&&c.body).length,1);
 ack(response(wrap(job())));await first;assert.equal(x.$('lm-job').hidden,false);assert.equal(x.calls.at(-1).opts.headers.Authorization,'Bearer memory-secret');
});
for(const failure of [new Error('transport timeout'),response({schema_version:2,job:job()}),response({error:'internal',code:'internal',schema_version:1},500)]) {
 test('uncertain start retains exact tuple and resolves before explicit same-key retry',async()=>{
  const x=setup();await x.ready();await x.review();await x.start(failure);
  const tuple=JSON.parse([...x.storage.values()][0]).pending;assert.equal(x.$('lm-plan').disabled,true);assert.equal(x.$('lm-retry').hidden,true);
  x.queue.push(response({schema_version:1,error:'not found',code:'not_found'},404));await x.click('lm-resolve');assert.equal(x.$('lm-retry').hidden,false);
  x.queue.push(response(wrap(job())));await x.click('lm-retry');
  const starts=x.calls.filter(c=>c.url.endsWith('/jobs')&&c.body);assert.equal(starts.length,2);assert.deepEqual(starts[0].body,starts[1].body);assert.equal(starts[1].body.idempotency_key,tuple.idempotency_key);
 });
}
test('reload resolves original pending key read-only and reopens terminal partial evidence',async()=>{
 const x=setup();await x.ready();await x.review();await x.start(new Error('ack lost'));
 const y=setup({storage:x.storage});const r=result();y.queue.push(response(cap),response({schema_version:1,jobs:[]}),response(wrap(r.job)),response(r));await y.app.connect();
 assert.equal(y.calls.filter(c=>c.url.endsWith('/jobs')&&c.body).length,0);assert.equal(y.calls[2].url,'/api/v1/lm/resolve');assert.equal(y.$('lm-verdict').textContent,'Not evaluated');assert.match(y.$('lm-result-reason').textContent,/70 development attempts · 0 heldout/);assert.equal(y.$('lm-delta').hidden,true);
});
test('mismatched resolved specification cannot replace a pending identity',async()=>{
 const x=setup();await x.ready();await x.review();await x.start(new Error('lost'));
 x.queue.push(response(wrap(job({spec_sha256:'b'.repeat(64)}))));await x.click('lm-resolve');
 assert.equal(x.$('lm-plan').disabled,true);assert.match(x.$('lm-notice').textContent,/unsupported response/);assert.ok(JSON.parse([...x.storage.values()][0]).pending);
});
test('cancellation is explicit, shows cancelling until confirmed, and has no relaunch',async()=>{
 const x=setup();await x.ready();await x.review();await x.start();x.app.view(true);
 x.queue.push(response(wrap(job({status:'cancelling',updated_at:'2026-11-13T12:00:02Z'}))));await x.click('lm-cancel');
 assert.match(x.$('lm-notice').textContent,/not yet confirmed/);assert.equal(x.$('lm-cancel').disabled,true);
 x.queue.push(response(wrap(job({status:'cancelled',reason:'user_cancelled',updated_at:'2026-11-13T12:00:03Z'}))));await x.tick();
 assert.match(x.$('lm-job-title').textContent,/cancelled/);assert.equal(x.$('lm-cancel').hidden,true);
 assert.equal(x.calls.filter(c=>c.url.endsWith('/cancel')).length,1);assert.equal(x.calls.filter(c=>c.url.endsWith('/jobs')&&c.body).length,1);
});
test('poll errors back off 5/10/20 seconds, stop, and hidden tabs pause',async()=>{
 const x=setup();await x.ready();await x.review();await x.start();x.app.view(true);
 for(const expected of [5000,10000,20000]) {x.queue.push(new Error('offline'));await x.tick();assert.ok([...x.timers.values()].some(t=>t.ms===expected));}
 x.queue.push(new Error('offline'));await x.tick();assert.equal(x.timers.size,0);assert.match(x.$('lm-notice').textContent,/paused/);
 x.doc.hidden=true;x.events.visibilitychange();assert.equal(x.timers.size,0);x.doc.hidden=false;x.events.visibilitychange();assert.equal(x.timers.size,1);
});
test('late poll cannot overwrite a newly selected job',async()=>{
 const x=setup();await x.ready();await x.review();await x.start();x.app.view(true);let resolve;
 x.queue.push(()=>new Promise(r=>resolve=r));const old=x.tick();
 const next=job({id:'second-job'});x.queue.push(response({schema_version:1,jobs:[next]}));await x.click('lm-history-refresh');await x.$('lm-history').children[0].onclick();
 resolve(response(wrap(job({status:'failed'}))));await old;assert.match(x.$('lm-job-title').textContent,/second-job/);
});
test('70 development attempts and a cap never imply a selected edit; outputs stay inert',async()=>{
 const x=setup();await x.ready();await x.review();const r=result();r.attempts=JSON.parse(JSON.stringify(r.attempts));r.attempts[0].output='<img src=x onerror=alert(1)>';
 x.queue.push(response(wrap(r.job)),response(r));await x.start(null);
 assert.match(x.$('lm-result-reason').textContent,/not completed/);assert.equal(x.$('lm-original').textContent,'<img src=x onerror=alert(1)>');
 assert.equal(x.$('lm-evidence').hidden,false);assert.equal(x.$('lm-delta').hidden,true);assert.ok(x.$('lm-counts').children.length>=5);
 assert.equal(x.downloads.length,0);x.queue.push(response({schema_version:1,fixture:'SCRIPTED evidence attachment'}));await x.click('lm-evidence');assert.equal(x.downloads.length,1);assert.equal(x.calls.at(-1).body.kind,'evidence');
});
for(const verdict of ['no_improvement','inconclusive'])test('complete '+verdict+' remains an honest verdict',async()=>{
 const x=setup();await x.ready();await x.review();const r=result(job({status:'completed',result_available:true}));r.report.status='complete';r.report.verdict=verdict;
 x.queue.push(response(wrap(r.job)),response(r));await x.start(null);assert.equal(x.$('lm-verdict').textContent,verdict==='no_improvement'?'No improvement':'Inconclusive');assert.equal(x.$('lm-delta').hidden,true);
});
test('verified delta export requires explicit click and server availability; rollback instructions visible',async()=>{
 const x=setup();await x.ready();await x.review();const r=result(job({status:'completed',result_available:true,selected_delta_available:true}));r.report.verdict='inconclusive';
 x.queue.push(response(wrap(r.job)),response(r));await x.start(null);assert.equal(x.downloads.length,0);assert.equal(x.$('lm-delta').hidden,false);assert.equal(x.$('lm-rollback').hidden,false);
 x.queue.push(response({schema_version:1,fixture:'SCRIPTED verified export transport, not a useful edit'}));await x.click('lm-delta');assert.equal(x.calls.at(-1).body.kind,'selected_delta');assert.equal(x.downloads.length,1);
});
for(const [label,r] of [['old server',response({error:'route missing'},404)],['unauthorized',response({error:'unauthorized'},401)],['unavailable',response({...cap,available:false,reason:'Runtime not configured'})],['readonly',response({...cap,readonly:true})]])test(label+' shows setup with no Start',async()=>{
 const x=setup({queue:[r,response({schema_version:1,jobs:[]})]});await x.app.connect();assert.equal(x.$('lm-setup').hidden,false);assert.equal(x.$('lm-start').disabled,true);assert.ok(x.$('lm-notice').textContent.length>20);
});
test('static mode with arbitrary flags has zero transport/storage writes or executable handlers',async()=>{
 const storage=new Map();const x=setup({staticMode:true,storage});x.app.view(true);await x.app.connect();for(const id of ['lm-start','lm-cancel','lm-plan','lm-delta','lm-evidence','lm-resolve','lm-history-refresh'])assert.equal(x.$(id).onclick,undefined);
 assert.equal(x.calls.length,0);assert.equal(storage.size,0);assert.match(x.$('lm-notice').textContent,/static export/);
});
test('blocked session storage prevents Start dispatch',async()=>{
 const x=setup({storageFail:true});await x.ready();await x.review();await x.start();assert.equal(x.calls.filter(c=>c.url.endsWith('/jobs')&&c.body).length,0);assert.match(x.$('lm-notice').textContent,/storage is unavailable/);
});
for(const outcome of ['unsupported','clarification_required'])test(outcome+' is shown honestly and cannot Start',async()=>{
 const x=setup();await x.ready();x.queue.push(response({...plan,outcome,message:'Use a supported request',plan_id:null,spec_sha256:null,spec:null,expires_at:null}));await x.click('lm-plan');assert.equal(x.$('lm-review').hidden,true);assert.equal(x.$('lm-start').disabled,true);
});
test('altered spec hash cannot enter review',async()=>{
 const x=setup();await x.ready();x.queue.push(response({...plan,spec_sha256:'b'.repeat(64)}));await x.click('lm-plan');assert.equal(x.$('lm-review').hidden,true);assert.match(x.$('lm-notice').textContent,/unsupported response/);
});

test('a missing old-server resolve route cannot authorize a same-key retry',async()=>{
 const x=setup();await x.ready();await x.review();await x.start(new Error('lost acknowledgment'));
 x.queue.push(response({error:'Not Found'},404));await x.click('lm-resolve');
 assert.equal(x.$('lm-retry').hidden,true);assert.equal(x.$('lm-plan').disabled,true);
});
test('evidence-read failure after admission preserves known job instead of a new uncertain start',async()=>{
 const x=setup();await x.ready();await x.review();const j=result().job;
 x.queue.push(response(wrap(j)),new Error('evidence unavailable'));await x.start(null);
 const saved=JSON.parse([...x.storage.values()][0]);assert.equal(saved.pending,null);assert.equal(saved.job_id,j.id);
 assert.match(x.$('lm-notice').textContent,/job was admitted/);assert.equal(x.$('lm-recovery').hidden,true);
});
test('malformed attempt identity cannot become visible evidence',async()=>{
 const x=setup();await x.ready();await x.review();const r=result();r.attempts=JSON.parse(JSON.stringify(r.attempts));r.attempts[0].spec_sha256='f'.repeat(64);
 x.queue.push(response(wrap(r.job)),response(r));await x.start(null);
 assert.equal(x.$('lm-result').hidden,true);assert.match(x.$('lm-notice').textContent,/unsupported response/);
});
