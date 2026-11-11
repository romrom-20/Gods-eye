const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname,'../../godseye/static/app.js'),'utf8');
const live = source.slice(source.indexOf('// Live goal transport.'));

test('journey step follows review and admitted execution, including unknown activity and terminal failures', () => {
  const nodes = new Map();
  const $ = id => {if (!nodes.has(id)) nodes.set(id,{setAttribute(k,v){this[k]=v;},removeAttribute(k){delete this[k];}});return nodes.get(id);};
  const context = {$,run:null,pending:null,plan:null,busy:false,durable:true,ids:[],terminal:s=>['completed','failed','cancelled','interrupted'].includes(s)};
  vm.createContext(context);
  vm.runInContext(live.slice(live.indexOf('  function lock()'),live.indexOf('  function invalidate()')),context);
  const check = expected => {context.lock();for(let i=1;i<=4;i++)assert.equal($('goal-step-'+i)['aria-current'],i===expected?'step':undefined);assert.equal($('goal-request-layout').hidden,expected!==1);};
  check(1);context.plan={};check(2);context.pending={uncertain:true};check(3);
  context.run={status:'running'};check(3);context.run={status:'cancelling'};check(3);
  for(const status of ['completed','failed','cancelled','interrupted']){context.run={status};check(4);}
});

test('result leads with measured verdict, original, sample uncertainty and regression evidence', () => {
  const nodes = new Map();const $ = id => {if (!nodes.has(id)) nodes.set(id,{focus(){this.focused=true;}});return nodes.get(id);};
  const context = {$,save(){},lock(){},say(){},downloadBusy:false};vm.createContext(context);
  vm.runInContext(live.slice(live.indexOf('  function render(v)'),live.indexOf('  // Explicit checkpoint download')),context);
  const value={experiment_id:'run',spec_hash:'a'.repeat(64),status:'completed',verdict:'no_improvement',phase:{name:'unknown'},usage:{requests:2,input_tokens:12,output_tokens:4,tool_calls:3,elapsed_seconds:1,usage_complete:false,request_in_flight:true},evidence:{candidate_manifest_id:'artifact',paired_samples:8,mean_delta:-1,paired_se:0.5,min_control_delta:-2,limitations:['Small capped sample.']}};
  context.render(value);
  assert.match($('goal-result-title').textContent,/^No measured improvement/);
  for(const expected of ['Paired samples: 8','Mean score change: -1','standard error: 0.5','control mean change: -2','original is preserved','Small capped sample.'])assert.ok($('goal-result-text').textContent.includes(expected));
  assert.match($('goal-usage').textContent,/charges unknown.*billing may continue/);
  assert.equal($('goal-download').hidden,false);assert.equal($('goal-result-title').focused,true);
  for(const status of ['failed','cancelled','interrupted']){
    context.render({...value,status,verdict:'not_evaluated',evidence:null});
    assert.match($('goal-result-title').textContent,/^No measured result/);
    assert.equal($('goal-download').hidden,true);
    assert.match($('goal-result-text').textContent,/No complete measured evidence.*original is preserved/);
  }
});
