// Run: ego-browser nodejs < tests/browser/goal_journey.cjs
// First run goal_backend.py in a separate terminal. No real provider is contacted.
const assert = (condition, message) => { if (!condition) throw Error(message); };
const base = 'http://127.0.0.1:8879';
const task = await taskSpace('Bounded first-use browser journey');
console.log({spaceId:task.spaceId});
const page = task.page('p1');
const config = async body => {
  const r = await fetch(base+'/__fixture/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  assert(r.ok,'fixture configuration failed');
};
const stats = async () => (await fetch(base+'/__fixture/state')).json();
const text = id => page.evaluate(id => document.getElementById(id).textContent,id);
const waitText = (id,value) => page.waitForFunction(({id,value}) => document.getElementById(id).textContent.includes(value),{id,value},{timeout:20000});
async function open() {
  await page.goto(base+'/lab?browser-test=1');
  await waitText('goal-notice','Live experiment');
  await page.waitForFunction(() => typeof document.getElementById('goal-form').onsubmit === 'function');
}
async function review() {
  await page.fill('#goal-draft','Improve Breakout score');
  await page.evaluate(() => { document.getElementById('goal-advanced').open = true; });
  await page.fill('#goal-model','scripted-acceptance');
  for (const [id,value] of Object.entries({requests:40,rounds:40,calls:80,seconds:30,reply:100,tokens:10000})) await page.fill('#goal-'+id,String(value));
  await page.click('#goal-plan');
  await page.waitForSelector('#goal-review',{state:'visible'});
  assert(await page.evaluate(() => document.getElementById('goal-request-layout').hidden),'request did not yield to review');
}
async function start() { await page.click('#goal-consent'); await page.click('#goal-start'); }
async function reset() { await page.click('#goal-again'); }
async function finishRun() { await waitText('goal-result-title','completed'); }

await config({}); await open();
const before = await stats();
assert(await page.evaluate(() => !document.getElementById('goal-model').closest('details')),'required programmer hidden');
await page.cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),'mobile horizontal overflow');
await page.screenshot({path:'/tmp/godseye-first-use-mobile.png'});
await page.cdp('Emulation.clearDeviceMetricsOverride');
await page.fill('#goal-model','scripted-acceptance');
await page.fill('#goal-draft','Edit Qwen weights');
await page.click('#goal-plan'); await waitText('goal-status','Unsupported goal');
assert((await stats()).workers === before.workers,'unsupported request started work');
await page.fill('#goal-draft','Improve Breakout score');
await page.evaluate(() => {const input=document.getElementById('goal-requests');input.value='0';document.getElementById('goal-advanced').open=false;});
await page.click('#goal-plan');
assert(await page.evaluate(() => document.getElementById('goal-advanced').open && document.activeElement.id==='goal-requests'),'invalid advanced field not revealed and focused');
await page.fill('#goal-requests','4');
await page.focus('#goal-model'); await page.press('#goal-model','Tab');
assert(await page.evaluate(() => document.activeElement.tagName==='SUMMARY'),'keyboard cannot reach advanced controls');
await review();
assert((await stats()).workers === before.workers,'review started work');
assert((await text('goal-canonical')).includes('browser-suite'),'registered evaluation missing');
assert((await text('goal-evaluation')).includes('browser-suite'),'plain-language evaluation missing');
assert(await page.evaluate(() => document.querySelectorAll('#goal-limits li').length === 7),'seven reviewed limits missing');
assert(await page.evaluate(() => document.activeElement.id === 'goal-review-title' && document.getElementById('goal-step-2').getAttribute('aria-current') === 'step'),'review focus or progression missing');
await page.screenshot({path:'/tmp/godseye-first-use-review.png'});
await page.goto(base+'/lab?browser-test=reload-review');
assert(await page.evaluate(() => !document.getElementById('goal-consent').checked && document.getElementById('goal-review').hidden),'reload retained confirmation');
await review();
await page.click('#goal-edit');
await page.fill('#goal-requests','39');
assert(await page.evaluate(() => document.getElementById('goal-review').hidden && document.getElementById('goal-start').disabled),'edit did not invalidate');
await review(); await start();
// Dispatch duplicate handler calls in the actual browser, including disabled controls.
await page.evaluate(() => { document.getElementById('goal-start').onclick(); document.getElementById('goal-start').onclick(); });
await finishRun();
assert((await text('goal-result-title')).startsWith('No measured improvement'),'negative measured outcome missing');
assert(await page.evaluate(() => document.getElementById('goal-step-4').getAttribute('aria-current') === 'step'),'result progression missing');
assert((await text('goal-result-text')).includes('original is preserved'),'original preservation missing');
await page.screenshot({path:'/tmp/godseye-first-use-result.png'});
assert((await text('goal-result-text')).includes('Mean score change: 0'),'actual root selection measurement missing');
assert((await stats()).workers === before.workers+1,'duplicate start admitted twice');
assert(await page.evaluate(() => !document.querySelector('#goal-result a[download]')),'unavailable download exposed');
await page.goto(base+'/lab?browser-test=terminal'); await finishRun();
assert((await stats()).workers === before.workers+1,'reload relaunched');
await reset(); console.log('PASS review / invalidation / duplicate start / actual negative measurement / terminal reload');

await config({}); await review();
const expiryBefore = await stats();
const expired = await fetch(base+'/__fixture/expire',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
assert(expired.ok,'fixture expiry failed');
await start(); await waitText('goal-status','Start rejected before admission');
const expiredTuple = await page.evaluate(() => JSON.parse(sessionStorage.getItem('godseye.goal-live.v1')).pending.body);
assert((await stats()).workers===expiryBefore.workers,'expired plan admitted work');
await page.goto(base+'/lab?browser-test=expired-reload'); await waitText('goal-status','Previous Start acknowledgment');
await page.click('#goal-reconnect'); await waitText('goal-status','Start rejected before admission');
const rejectedStats = await stats();
await page.click('#goal-review-again');
assert(await page.evaluate(() => !document.getElementById('goal-draft').disabled && !document.getElementById('goal-consent').checked && document.getElementById('goal-review').hidden && JSON.parse(sessionStorage.getItem('godseye.goal-live.v1')).pending === null),'review again failed to clear rejected attempt and confirmation');
assert((await stats()).requests.length===rejectedStats.requests.length,'Review again sent a request');
await page.evaluate(() => document.getElementById('goal-start').onclick());
assert((await stats()).workers===expiryBefore.workers,'review again silently started work');
await review();
assert((await stats()).workers===expiryBefore.workers,'fresh review started work');
await start(); await finishRun();
const recoveryStarts=(await stats()).requests.filter(x=>x.operation==='start').slice(-3);
assert(recoveryStarts[0].body.idempotency_key===expiredTuple.idempotency_key && recoveryStarts[1].body.idempotency_key===expiredTuple.idempotency_key,'expired tuple changed before recovery');
assert(recoveryStarts[2].body.draft_id!==expiredTuple.draft_id,'recovery reused expired draft');
assert((await stats()).workers===expiryBefore.workers+1,'recovery failed to admit exactly one fresh run');
await reset(); console.log('PASS real expired-plan rejection / reload / explicit Review again / fresh review and confirmation');

await config({drop:true,block:true}); await review(); const prior = await stats(); await start();
await waitText('goal-status','Admission may have committed');
assert(await page.evaluate(() => document.getElementById('goal-review-again').hidden),'uncertain admission offered Review again');
const tuple = await page.evaluate(() => JSON.parse(sessionStorage.getItem('godseye.goal-live.v1')).pending.body);
await page.goto(base+'/lab?browser-test=lost-start'); await waitText('goal-status','Previous Start acknowledgment');
const afterReload = await stats(); assert(afterReload.requests.filter(x=>x.operation==='start').length === prior.requests.filter(x=>x.operation==='start').length+1,'reload retried unknown mutation');
await page.click('#goal-reconnect'); await waitText('goal-phase','Activity unavailable');
assert((await stats()).workers === prior.workers+1,'reconcile admitted twice');
const starts = (await stats()).requests.filter(x=>x.operation==='start').slice(-2);
assert(JSON.stringify(starts[0].body) === JSON.stringify(starts[1].body),'reconcile changed tuple');
assert(starts[1].body.idempotency_key === tuple.idempotency_key,'key changed');
await page.goto(base+'/lab?browser-test=running'); await waitText('goal-phase','running');
assert((await stats()).workers === prior.workers+1,'running reload relaunched');
await page.click('#goal-cancel'); await waitText('goal-phase','cancelling');
await page.goto(base+'/lab?browser-test=cancelling'); await waitText('goal-phase','cancelling');
await fetch(base+'/__fixture/release',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
await waitText('goal-result-title','cancelled');
assert((await text('goal-result-text')).includes('No complete measured evidence'),'cancel fabricated evidence');
await reset(); console.log('PASS lost start / retained tuple / explicit reconcile / unknown progress / cancel acknowledgment / cancelling reload');

await config({operation:'start',errors:['queue_full','rate_limited','worker_unavailable','queue_full']});
await review(); const retryBefore = await stats(); await start();
// Assert the real 5/10/20 second HTTP backoff, without altering browser clocks.
await page.waitForFunction(() => document.getElementById('goal-status').textContent.includes('Service: queue_full'),undefined,{timeout:45000});
const retryAfter = await stats();
const retries = retryAfter.requests.slice(retryBefore.requests.length).filter(x=>x.operation==='start');
assert(retries.length===4,'retry loop did not stop after three additional attempts');
assert(retries.every(x=>JSON.stringify(x.body)===JSON.stringify(retries[0].body)),'retry tuple changed');
assert(retryAfter.workers===retryBefore.workers,'rejected admission ran worker');
await page.goto(base+'/lab?browser-test=retry-reload'); await waitText('goal-status','Previous Start acknowledgment');
assert((await stats()).requests.length===retryAfter.requests.length,'reload reset retry counter');
await page.click('#goal-reconnect'); await finishRun(); await reset();
console.log('PASS shared bounded 5/10/20 backoff across error codes / no retry after reload / explicit recovery');

await config({mode:'spin'}); await review();
await page.evaluate(() => { const e=document.getElementById('goal-requests'); e.value='1'; e.dispatchEvent(new Event('input',{bubbles:true})); });
await page.click('#goal-plan'); await page.waitForSelector('#goal-review',{state:'visible'}); await start();
await waitText('goal-result-title','failed');
assert((await text('goal-status')).includes('budget_exhausted'),'budget failure lost reason');
assert((await text('goal-result-text')).includes('No complete measured evidence'),'budget failure fabricated evidence');
await reset(); console.log('PASS actual adapter budget stop');

await config({operation:'plan',errors:['unavailable']});
await page.click('#goal-plan');
await waitText('goal-status','Service: unavailable');
assert(await page.evaluate(() => document.getElementById('goal-draft').value === 'Improve Breakout score' && document.getElementById('goal-review').hidden),'unavailable lost draft or enabled start');
console.log('PASS unavailable service preserves draft');

await page.goto(base+'/lab?goalMode=mock'); await page.click('#goal-example');
const mockBefore = await stats(); await page.click('#goal-plan'); await start(); await page.click('#goal-next');
assert((await stats()).requests.length===mockBefore.requests.length,'mock contacted experiment service');
console.log('PASS mock transport separation');
await page.goto(base+'/lab#overview');
await page.waitForFunction(() => !document.getElementById('quick-experiment').disabled);
const cpuBefore = await stats(); await page.click('#quick-experiment');
await page.waitForFunction(() => document.getElementById('eval-status').textContent.includes('Evaluation completed and saved.'),undefined,{timeout:45000});
assert((await stats()).workers===cpuBefore.workers,'CPU example contacted programmer worker');
assert((await stats()).original_preserved,'original checkpoint changed');
console.log('PASS one-click CPU example completed and saved; original preserved');
await task.finish({keep:[]});
