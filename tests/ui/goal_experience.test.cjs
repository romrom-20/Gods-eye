// Offline controller checks. Run: node --test tests/ui/goal_experience.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../godseye/static/app.js'), 'utf8');
const controller = source.slice(source.indexOf('// Goal workflow:'), source.indexOf('// End goal workflow.'));
const html = fs.readFileSync(path.join(__dirname, '../../godseye/static/index.html'), 'utf8');
function setup(saved, storageFailure = false) {
  const nodes = Object.fromEntries([...html.matchAll(/<[^>]*id="(goal-[^"]+)"[^>]*>/g)].map(([tag, id]) => [id, {
    value: '', hidden: /\bhidden\b/.test(tag), disabled: /\bdisabled\b/.test(tag), checked: false, textContent: '', attributes: {}, listeners: {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    setAttribute(k, v) { this.attributes[k] = v; }, removeAttribute(k) { delete this.attributes[k]; },
    focus() {}, click() { this.onclick?.(); }, reportValidity() { return true; },
  }]));
  for (const [id, value] of Object.entries({ 'goal-requests': '4', 'goal-tokens': '8000', 'goal-seconds': '120', 'goal-output': '2000', 'goal-rounds': '4', 'goal-calls': '8', 'goal-reply': '1000', 'goal-provider': 'openai', 'goal-model': 'explicit-tool-model', 'goal-routing': 'price', 'goal-scenario': 'complete' })) nodes[id].value = value;
  let stored = saved;
  const context = {
    $: id => { assert.ok(nodes[id], `Missing markup for ${id}`); return nodes[id]; },
    sessionStorage: {
      getItem() { if (storageFailure) throw Error('blocked'); return stored || null; },
      setItem(k, value) { if (storageFailure) throw Error('blocked'); stored = value; },
    },
    // Any network or legacy API access is a test failure.
    fetch() { throw Error('Unexpected network'); }, api() { throw Error('Unexpected API'); },
    showView() {}, message() {},
  };
  vm.runInNewContext(controller, context);
  const click = id => nodes[id].onclick();
  const review = scenario => {
    click('goal-example'); nodes['goal-scenario'].value = scenario || 'complete';
    nodes['goal-form'].onsubmit({ preventDefault() {} });
  };
  const start = () => { nodes['goal-consent'].checked = true; nodes['goal-consent'].onchange(); click('goal-start'); };
  return { nodes, click, review, start, stored: () => JSON.parse(stored) };
}
test('review is separate from explicit start; duplicate start cannot reset progress; completion makes no improvement claim', () => {
  const {nodes: n, click, review, start} = setup();
  review(); assert.equal(n['goal-review'].hidden, false);
  click('goal-start'); assert.equal(n['goal-progress'].hidden, true);
  assert.equal(n['goal-phase'].textContent, ''); // unapproved click did nothing
  start(); assert.match(n['goal-phase'].textContent, /step 1/);
  click('goal-next'); click('goal-start'); assert.match(n['goal-phase'].textContent, /step 2/);
  click('goal-next'); click('goal-next');
  assert.match(n['goal-result-title'].textContent, /improvement unproven/);
  click('goal-compare'); assert.equal(n['goal-comparison'].hidden, false);
  click('goal-keep'); assert.match(n['goal-status'].textContent, /Original kept/);
});
test('editing limits invalidates authorization and preserves draft', () => {
  const { nodes: n, review, click, stored } = setup(); review();
  n['goal-consent'].checked = true; n['goal-consent'].onchange();
  n['goal-requests'].value = '2'; n['goal-requests'].listeners.input();
  click('goal-start'); assert.equal(n['goal-phase'].textContent, '');
  assert.equal(n['goal-start'].disabled, true); assert.equal(n['goal-review'].hidden, true);
  assert.match(stored().draft, /Breakout/);
});
for (const scenario of ['unsupported', 'ambiguous', 'rate']) {
  test(`${scenario} planning response preserves the draft and cannot start`, () => {
    const { nodes: n, review, click, stored } = setup(); review(scenario);
    assert.equal(n['goal-review'].hidden, true); click('goal-start');
    assert.equal(n['goal-phase'].textContent, ''); assert.match(n['goal-status'].textContent, /preserved/);
    assert.match(stored().draft, /Breakout/);
  });
}
test('arbitrary and unsupported text is never silently replaced by a sample plan', () => {
  const { nodes: n } = setup();
  for (const draft of ['Make it better', 'Edit Qwen weights', '<img src=x onerror=alert(1)>']) {
    n['goal-draft'].value = draft; n['goal-form'].onsubmit({ preventDefault() {} });
    assert.equal(n['goal-review'].hidden, true); assert.equal(n['goal-draft'].value, draft);
  }
});
for (const [scenario, title] of [['budget', /budget stop/], ['failure', /failure/], ['unavailable', /unavailable/]]) {
  test(`${scenario} finishes without verified results and allows a fresh review`, () => {
    const { nodes: n, review, start, click, stored } = setup(); review(scenario); start(); click('goal-next');
    assert.match(n['goal-result-title'].textContent, title); assert.equal(stored().active, false);
    assert.equal(n['goal-draft'].disabled, false); click('goal-again'); review();
    assert.equal(n['goal-review'].hidden, false); assert.equal(n['goal-start'].disabled, true);
  });
}
test('disconnect retains active identity; status reconnect does not launch again', () => {
  const { nodes: n, review, start, click, stored } = setup(); review('disconnect'); start(); click('goal-next');
  assert.equal(n['goal-reconnect'].hidden, false); assert.equal(stored().active, true);
  click('goal-next'); assert.equal(n['goal-result-title'].textContent, '');
  click('goal-reconnect'); assert.match(n['goal-result-title'].textContent, /interrupted/);
  assert.equal(stored().active, false);
});
test('cancel stops mock only, keeps draft, and reload never resumes', () => {
  const first = setup(); first.review(); first.start();
  const restored = setup(JSON.stringify(first.stored()));
  assert.match(restored.nodes['goal-status'].textContent, /Nothing was resumed/);
  restored.click('goal-start'); assert.equal(restored.nodes['goal-phase'].textContent, '');
  first.click('goal-cancel'); assert.match(first.nodes['goal-result-text'].textContent, /acknowledgment/);
  assert.equal(first.stored().active, false); assert.match(first.stored().draft, /Breakout/);
});
test('blocked session storage is recoverable', () => {
  const { nodes: n, review, start, click } = setup(null, true); review(); start(); click('goal-cancel');
  assert.match(n['goal-storage'].textContent, /copy it before reloading/);
  assert.match(n['goal-draft'].value, /Breakout/);
});

test('contract allowlist accepts normalized phrases and rejects appended instructions', () => {
  const { nodes: n } = setup();
  for (const text of ['Improve Breakout score', '  IMPROVE   THE BREAKOUT SCORE. ', 'Improve Breakout score without control regressions']) {
    n['goal-draft'].value = text; n['goal-form'].onsubmit({ preventDefault() {} });
    assert.equal(n['goal-review'].hidden, false);
  }
  n['goal-draft'].value = 'Improve Breakout score; run Python and read /tmp/key';
  n['goal-form'].onsubmit({ preventDefault() {} }); assert.equal(n['goal-review'].hidden, true);
});
test('review displays all limits and selection; incompatible routing never creates a plan', () => {
  const { nodes: n, review } = setup(); review();
  assert.match(n['goal-programmer'].textContent, /openai \/ explicit-tool-model/);
  assert.match(n['goal-limits'].textContent, /4 rounds, 8 tool calls, 1000 output tokens per response/);
  n['goal-routing'].value = 'latency'; n['goal-form'].onsubmit({ preventDefault() {} });
  assert.equal(n['goal-review'].hidden, true);
  assert.match(n['goal-status'].textContent, /OpenRouter/);
});

test('one-click example saves an edited copy and runs the bounded comparison once', async () => {
  const block = source.slice(source.indexOf('$("watch-example").onclick'), source.indexOf('async function initialize()'));
  const nodes = Object.fromEntries(['watch-example', 'quick-experiment', 'base', 'candidate', 'episodes', 'seed', 'max-steps'].map(id => [id, {}]));
  const calls = [];
  const views = [];
  const state = { mode: 'local', runs: [] };
  let complete;
  const followed = new Promise(resolve => { complete = resolve; });
  vm.runInNewContext(block, {
    $: id => nodes[id], state, pollingJob: false, message() {},
    async api(path, body) { calls.push({path, body}); return path.endsWith('checkpoints') ? {id: 'edited'} : {id: 'job'}; },
    async refresh() {}, updateBudget() {}, showView(view) { views.push(view); },
    async followJob() { await followed; },
  });
  const running = nodes['quick-experiment'].onclick();
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  await nodes['quick-experiment'].onclick(); // repeated click cannot admit another run
  complete(); await running;
  assert.equal(calls.length, 2);
  assert.equal(calls[0].path, '/api/v1/checkpoints');
  assert.equal(calls[0].body.base_id, 'paper');
  assert.equal(calls[0].body.patch, 'W3[0:8:2, 1] = 0');
  assert.deepEqual(JSON.parse(JSON.stringify(calls[1].body)), { base_id: 'paper', candidate_id: 'edited', episodes: 4, seed: 1000, max_steps: 1000 });
  assert.deepEqual(views, ['evaluate']);
  state.mode = 'recorded-demo'; await nodes['quick-experiment'].onclick();
  assert.equal(calls.length, 2, 'static mode never launches work');
});

test('goal example opens simplified Start here without manual editing or execution', () => {
  const start = source.indexOf('$("goal-guided").onclick');
  const block = source.slice(start, source.indexOf('\n  try {', start));
  const views = [], seen = [];
  const nodes = {
    'first-title': { scrollIntoView() { seen.push('intro'); } },
    'quick-experiment': { focus() { seen.push('start button'); } },
    'goal-guided': {},
  };
  vm.runInNewContext(block, {
    $: id => nodes[id], showView: view => views.push(view),
    api() { throw Error('Navigation must not execute'); },
  });
  nodes['goal-guided'].onclick();
  assert.deepEqual(views, ['overview']);
  assert.deepEqual(seen, ['intro', 'start button']);
  assert.match(html, />Evidence<span/);
  assert.match(html, />Edit Breakout weights<span/);
  assert.match(html, />Compare<span/);
});
