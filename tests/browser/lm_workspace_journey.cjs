// ego-browser nodejs < tests/browser/lm_workspace_journey.cjs
// Dedicated lm_workspace_backend.py port 18996. SCRIPTED transport, no model execution.
const assert=(v,m)=>{if(!v)throw Error(m);};
const base='http://127.0.0.1:18996';
const task=await taskSpace('Qwen workspace scripted UI');
const page=task.page('p1');
console.log({spaceId:task.spaceId,page:page.label,fixture:'SCRIPTED UI TRANSPORT; no model execution'});
const config=async mode=>{const r=await fetch(base+'/__fixture/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})});assert(r.ok,'fixture configuration');};
const state=async()=>await(await fetch(base+'/__fixture/state')).json();
const noOverflow=async()=>assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'horizontal page overflow');
await config('budget');await page.goto(base+'/lab#language-model');await page.waitForSelector('#lm-controls',{state:'visible'});
assert(await page.evaluate(()=>getComputedStyle(document.querySelector('.experiment-layout')).display==='none'),'Breakout layout must be hidden');
const before=(await state()).starts;
await page.click('#lm-sample');await page.click('#lm-plan');await page.waitForSelector('#lm-review',{state:'visible'});
assert((await state()).starts===before,'preview started execution');
assert(await page.evaluate(()=>document.activeElement.id==='lm-review-title'),'review heading focus');
await page.screenshot({path:'/tmp/qwen-scripted-desktop-review.png'});await noOverflow();
await page.focus('#lm-consent');await page.press('#lm-consent','Space');await page.press('#lm-consent','Tab');
assert(await page.evaluate(()=>document.activeElement.id==='lm-start'),'keyboard cannot reach Start');
await page.press('#lm-start','Enter');await page.waitForSelector('#lm-job',{state:'visible'});
assert((await state()).starts===before+1,'Start admission count');
await page.screenshot({path:'/tmp/qwen-scripted-desktop-running.png'});
await page.click('#lm-refresh');await page.click('#lm-refresh');
await page.waitForSelector('#lm-result',{state:'visible'});
assert(await page.evaluate(()=>document.querySelector('#lm-verdict').textContent==='Not evaluated'&&document.querySelector('#lm-result-reason').textContent.includes('70 development attempts · 0 heldout')&&document.querySelector('#lm-delta').hidden),'incomplete result overstated');
await page.evaluate(()=>document.querySelector('#lm-result').scrollIntoView());
await page.screenshot({path:'/tmp/qwen-scripted-desktop-result.png'});
await page.selectOption('#lm-variant','decoding');await page.selectOption('#lm-case','dev-inventory');
assert(await page.evaluate(()=>document.querySelector('#lm-candidate').textContent.includes('Explanation:')&&document.querySelector('#lm-candidate-score').textContent.includes('budget limited')),'capped actual output missing');
await page.evaluate(()=>document.querySelector('.lm-output-pair').scrollIntoView());
await page.screenshot({path:'/tmp/qwen-scripted-desktop-responses.png'});
const dl=page.waitForEvent('download');await page.click('#lm-evidence');const download=await dl;await download.saveAs('/tmp/qwen-scripted-evidence.json');
assert((await state()).starts===before+1,'inspection/download started inference');
await page.reload();await page.waitForSelector('#lm-result',{state:'visible'});
assert((await state()).starts===before+1,'reload started inference');
await page.cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
await page.evaluate(()=>window.scrollTo(0,0));await noOverflow();await page.screenshot({path:'/tmp/qwen-scripted-mobile-workspace.png'});
await page.evaluate(()=>document.querySelector('#lm-result').scrollIntoView());await noOverflow();await page.screenshot({path:'/tmp/qwen-scripted-mobile-result.png'});
await page.selectOption('#lm-variant','decoding');await page.selectOption('#lm-case','dev-inventory');await page.evaluate(()=>document.querySelector('.lm-output-pair').scrollIntoView());await noOverflow();await page.screenshot({path:'/tmp/qwen-scripted-mobile-responses.png'});
await page.cdp('Emulation.clearDeviceMetricsOverride');
// Acknowledge loss: reload reconciles, with no fresh key or second admission.
await config('lost_ack');await page.click('#lm-sample');await page.click('#lm-plan');await page.click('#lm-consent');await page.click('#lm-start');
await page.waitForSelector('#lm-recovery',{state:'visible'});
const lost=(await state()).starts;
assert(await page.evaluate(()=>document.querySelector('#lm-retry').hidden),'offered retry before resolve');
await page.reload();await page.waitForSelector('#lm-job',{state:'visible'});
assert((await state()).starts===lost,'uncertain start relaunched on refresh');
// Explicit cancellation remains cancelling until a read-only status confirms exit.
await config('running');await page.click('#lm-cancel');
await page.waitForFunction(()=>document.querySelector('#lm-job-title').textContent.startsWith('cancelling'));
assert(await page.evaluate(()=>document.querySelector('#lm-job-title').textContent.startsWith('cancelling')),'cancellation claimed before confirmation');
await page.click('#lm-refresh');await page.waitForFunction(()=>document.querySelector('#lm-job-title').textContent.startsWith('cancelled'));
await page.goto(base+'/lab#overview');await page.waitForSelector('.experiment-node');
assert(await page.evaluate(()=>getComputedStyle(document.querySelector('.experiment-layout')).display!=='none'),'Breakout workspace not restored');
// The actual static export, including adversarial mock flags, must make zero API requests.
const calls=(await state()).calls.length;
await page.goto(base+'/recorded/lab.html?goalMode=mock&lmMode=mock#language-model');await page.waitForFunction(()=>document.querySelector('#lm-notice').textContent.includes('static export'));
assert(await page.evaluate(()=>!document.querySelector('#lm-controls').offsetHeight&&document.querySelector('#lm-connect').hidden),'static executable actions');
assert(await page.evaluate(()=>performance.getEntriesByType('resource').every(r=>!new URL(r.name).pathname.startsWith('/api/'))),'static API request in performance log');
assert((await state()).calls.length===calls,'static export contacted API');
await page.screenshot({path:'/tmp/qwen-static-local-only.png'});
for(const mode of ['unavailable','readonly','old','unauthorized']) {
 await config(mode);await page.goto(base+'/lab#language-model');await page.waitForSelector('#lm-setup',{state:'visible'});
 assert(await page.evaluate(()=>document.querySelector('#lm-start').disabled&&document.querySelector('#lm-notice').textContent.length>20),'setup state lost');
}
console.log('PASS SCRIPTED: review/keyboard explicit Start, historical 70-attempt token cap, no selected edit, response comparison, evidence download, reload/read-only reconciliation, cancellation, Breakout restore, desktop/mobile no overflow, actual 13-file static export zero API, setup states.');
await task.finish({keep:[]});
