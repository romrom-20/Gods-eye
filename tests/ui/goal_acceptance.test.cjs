// Acceptance of the existing MOCK only. No browser/service integration claim.
// Run: node --test tests/ui/goal_acceptance.test.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const app = fs.readFileSync(path.join(__dirname, '../../godseye/static/app.js'), 'utf8');
const start = app.indexOf('// Goal workflow:');
const end = app.indexOf('// End goal workflow.');
assert.ok(start >= 0 && end > start, 'Mock controller boundaries must exist');
const controller = app.slice(start, end);
const html = fs.readFileSync(path.join(__dirname, '../../godseye/static/index.html'), 'utf8');
const limitIds = ['requests', 'tokens', 'output', 'seconds', 'rounds', 'calls', 'reply'];
function fixture(saved) {
  let storage = saved || null;
  const nodes = Object.fromEntries([...html.matchAll(/<[^>]*id="(goal-[^"]+)"[^>]*>/g)].map(([tag, id]) => {
    const node = {
      value: '', hidden: /\bhidden\b/.test(tag), disabled: /\bdisabled\b/.test(tag),
      checked: false, textContent: '', listeners: {}, attributes: {},
      addEventListener(type, fn) { this.listeners[type] = fn; },
      setAttribute(k, v) { this.attributes[k] = v; }, removeAttribute(k) { delete this.attributes[k]; },
      focus() {}, reportValidity() { return true; },
    };
    Object.defineProperty(node, 'innerHTML', {set() { assert.fail('Goal content must be inert text'); }});
    return [id, node];
  }));
  const values = ['4', '8000', '2000', '120', '4', '8', '1000'];
  limitIds.forEach((name, i) => { nodes['goal-' + name].value = values[i]; });
  Object.assign(nodes['goal-provider'], {value: 'openai'});
  Object.assign(nodes['goal-model'], {value: 'explicit-tool-model'});
  Object.assign(nodes['goal-routing'], {value: 'price'});
  Object.assign(nodes['goal-scenario'], {value: 'complete'});
  let io = 0;
  const forbid = () => { io++; assert.fail('Mock must not access network, timers, keys or downloads'); };
  vm.runInNewContext(controller, {
    $: id => { assert.ok(nodes[id], `Missing node ${id}`); return nodes[id]; },
    sessionStorage: {getItem: () => storage, setItem: (key, value) => { storage = value; }},
    localStorage: new Proxy({}, {get: forbid}),
    fetch: forbid, api: forbid, XMLHttpRequest: forbid, WebSocket: forbid,
    setTimeout: forbid, setInterval: forbid, requestAnimationFrame: forbid,
    URL: {createObjectURL: forbid}, showView() {},
  });
  const click = id => nodes['goal-' + id].onclick();
  const submit = () => nodes['goal-form'].onsubmit({preventDefault() {}});
  const review = scenario => { click('example'); nodes['goal-scenario'].value = scenario || 'complete'; submit(); };
  const confirm = () => { nodes['goal-consent'].checked = true; nodes['goal-consent'].onchange(); click('start'); };
  return {nodes, click, review, confirm, submit, stored: () => JSON.parse(storage), io: () => io};
}

test('A01 mock journey reviews all limits, explicitly starts once, inspects unproven outcome and keeps original', () => {
  const f = fixture(), n = f.nodes;
  f.review();
  assert.equal(n['goal-review'].hidden, false);
  assert.match(n['goal-programmer'].textContent, /openai \/ explicit-tool-model/);
  assert.match(n['goal-limits'].textContent, /4 programmer requests, 8,000 reported input tokens, 2,000 reported output tokens, 120 seconds, 4 rounds, 8 tool calls, 1000 output tokens per response/);
  assert.match(n['goal-status'].textContent, /has not started/);
  f.click('start'); assert.equal(n['goal-progress'].hidden, true);
  f.confirm(); f.click('next'); f.click('start');
  assert.match(n['goal-phase'].textContent, /Sample step 2/);
  f.click('next'); f.click('next');
  assert.match(n['goal-result-title'].textContent, /improvement unproven/);
  assert.match(n['goal-result-text'].textContent, /no measured scores, regression checks, or edited artifacts/);
  f.click('compare'); assert.equal(n['goal-comparison'].hidden, false);
  f.click('keep'); assert.match(n['goal-status'].textContent, /No model was changed/);
  assert.equal(f.io(), 0);
});

test('A02 every editable selection or limit invalidates review and confirmation', () => {
  for (const id of ['draft', 'provider', 'model', 'routing', ...limitIds]) {
    const f = fixture(), n = f.nodes;
    f.review(); n['goal-consent'].checked = true; n['goal-consent'].onchange();
    n['goal-' + id].listeners.input();
    f.click('start');
    assert.equal(n['goal-review'].hidden, true, id);
    assert.equal(n['goal-start'].disabled, true, id);
    assert.equal(n['goal-consent'].checked, false, id);
    assert.equal(n['goal-progress'].hidden, true, id);
  }
});

test('A03 unsupported, clarification and rate-limit scenarios retain draft without execution', () => {
  for (const scenario of ['unsupported', 'ambiguous', 'rate']) {
    const f = fixture(), n = f.nodes;
    f.review(scenario); f.confirm();
    assert.equal(n['goal-review'].hidden, true);
    assert.equal(n['goal-progress'].hidden, true);
    assert.match(f.stored().draft, /Breakout/);
    assert.equal(f.io(), 0);
  }
});

test('A04 budget, provider failure, cancellation and disconnection never imply a measured improvement', () => {
  for (const scenario of ['budget', 'failure', 'unavailable', 'disconnect', 'cancel']) {
    const f = fixture(), n = f.nodes;
    f.review(scenario === 'cancel' ? 'complete' : scenario); f.confirm();
    if (scenario === 'cancel') f.click('cancel');
    else {
      f.click('next');
      if (scenario === 'disconnect') {
        assert.match(n['goal-phase'].textContent, /unknown/);
        assert.equal(f.stored().active, true);
        f.click('reconnect');
      }
    }
    assert.equal(n['goal-result'].hidden, false);
    assert.match(n['goal-result-text'].textContent, /sample response. No experiment ran/);
    assert.equal(f.stored().active, false);
    assert.equal(f.io(), 0);
  }
});

test('A05 reload restores draft/limits and discards even forged saved authorization', () => {
  const first = fixture(); first.review(); first.confirm();
  const saved = {...first.stored(), confirmed: true, spec_hash: 'fake', experiment_id: 'fake'};
  const f = fixture(JSON.stringify(saved)), n = f.nodes;
  assert.equal(n['goal-draft'].value, first.nodes['goal-draft'].value);
  for (const id of limitIds) assert.equal(n['goal-' + id].value, first.nodes['goal-' + id].value);
  assert.equal(n['goal-consent'].checked, false);
  assert.equal(n['goal-start'].disabled, true);
  assert.match(n['goal-status'].textContent, /Nothing was resumed or relaunched/);
  f.click('start'); assert.equal(n['goal-progress'].hidden, true);
  assert.equal(f.io(), 0);
});

test('A06 request markup remains inert and the walkthrough saves only draft preferences', () => {
  const f = fixture(), n = f.nodes;
  n['goal-draft'].value = '<img src=x onerror=alert(1)> Improve Breakout score'; f.submit();
  assert.equal(n['goal-review'].hidden, true);
  assert.match(n['goal-draft'].value, /<img/);
  f.review(); f.confirm();
  assert.deepEqual(Object.keys(f.stored()).sort(),
    ['draft', 'provider', 'model', 'routing', 'active', ...limitIds].sort());
  assert.equal(f.io(), 0);
});
