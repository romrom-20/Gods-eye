const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname,'../../godseye/static/app.js'),'utf8');
const perform = source.slice(source.indexOf('  async function perform(fn)'),source.indexOf('  // Replace sample-only copy'));

for (const pending of [null,{body:{idempotency_key:'original'},uncertain:true}]) {
  test('unavailable setup help retains '+(pending?'pending admission identity':'draft')+' and never retries',async()=>{
    const nodes = new Map();const $=id=>{if(!nodes.has(id))nodes.set(id,{hidden:true});return nodes.get(id);};
    const status=[];const tuple=JSON.stringify(pending);
    const context={$,pending,run:null,busy:false,timer:null,clearTimeout(){},lock(){},say:s=>status.push(s)};
    vm.createContext(context);vm.runInContext(perform,context);
    let calls=0;
    await context.perform(async()=>{calls++;throw Error('<img src=x onerror=secret()>');});
    assert.equal(calls,1);assert.equal($('goal-setup-help').hidden,false);
    assert.equal(JSON.stringify(context.pending),tuple);
    assert.ok(status.every(s=>!s.includes('<img')));
    if(pending)assert.match(status[0],/Admission may have committed.*reconcile/);
    await context.perform(async()=>{throw Object.assign(Error('unavailable'),{safe:true});});
    assert.equal($('goal-setup-help').hidden,false);
    assert.match(status.at(-1),pending?/reconcile/:/setup guide.*no-key CPU example/);
    assert.equal(JSON.stringify(context.pending),tuple);
    await context.perform(async()=>{});
    assert.equal($('goal-setup-help').hidden,true);
  });
}

test('no-key escape navigates without changing saved run or launching requests',()=>{
  const start=source.indexOf("  $('goal-guided').onclick = $('goal-setup-example').onclick");
  const handler=source.slice(start,source.indexOf('\n',start));
  const nodes={'goal-guided':{},'goal-setup-example':{},'quick-experiment':{focus(){}}};
  const views=[];const pending={body:{idempotency_key:'original'}};
  vm.runInNewContext(handler,{$:id=>nodes[id],pending,showView:v=>views.push(v),fetch(){throw Error('Unexpected request');}});
  nodes['goal-setup-example'].onclick();
  assert.deepEqual(views,['overview']);assert.equal(pending.body.idempotency_key,'original');
  const html=fs.readFileSync(require('node:path').join(__dirname,'../../godseye/static/index.html'),'utf8');
  assert.match(html,/aria-label="Experiment setup help"/);
  assert.match(html,/href="https:\/\/github.com\/romrom-20\/Gods-eye\/blob\/main\/docs\/local-operator-setup.md"/);
});
