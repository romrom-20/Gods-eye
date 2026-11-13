// Run ONLY under the separately authorized one-run integration task:
// ego-browser nodejs < tests/browser/lm_workspace_real_journey.cjs
// Actual create_app/LMService on dedicated port 18997. No intercepted LM responses.
// Existing admission is reused read-only on later invocations; the durable intent
// marker prevents another Start even if its first acknowledgment is uncertain.
const fs=await import('node:fs/promises');
const {isDeepStrictEqual}=await import('node:util');
const {createHash}=await import('node:crypto');
const assert=(v,m)=>{if(!v)throw Error(m);};
const base='http://127.0.0.1:18997';
const root='/tmp/godseye-lm-browser-integration-20261113-01';
const task=await taskSpace('Qwen real service integration');const page=task.page('p1');
console.log({spaceId:task.spaceId,purpose:'Authorized transport reproduction, not independent quality evidence'});
const get=async path=>{const r=await fetch(base+path);assert(r.ok,'HTTP '+r.status+' '+path);return r.json();};
const state=()=>get('/__integration/state');
const terminal=j=>['completed','failed','cancelled','interrupted'].includes(j.status);
const record=async(name,data)=>fs.writeFile(root+'/'+name,JSON.stringify(data,null,2)+'\n');
await page.goto(base+'/lab#language-model');await page.waitForSelector('#lm-controls',{state:'visible'});
let initial=await state();assert(initial.jobs.length<=1,'More than one real job');
if(initial.jobs.length===0) {
 assert(initial.journals.length===0,'Pre-start generations exist');
 assert(initial.audit.filter(c=>c.path==='/api/v1/lm/jobs'&&c.method==='POST').length===0,'A start was already attempted');
 await page.click('#lm-sample');await page.click('#lm-plan');await page.waitForSelector('#lm-review',{state:'visible'});
 assert(await page.evaluate(()=>document.activeElement.id==='lm-review-title'),'Review did not focus heading');
 assert(await page.evaluate(()=>document.querySelector('#lm-spec').textContent.includes('3a49a9cd1b743ba8935582e1e22673bf402d80e68a6136e559dd75fdf73aa08d')),'Exact canonical spec review failed');
 const preview=await state();assert(preview.jobs.length===0&&preview.journals.length===0,'Preview created execution');
 await record('prestart-proof.json',{page_load_jobs:initial.jobs.length,page_load_journals:initial.journals.length,preview_jobs:preview.jobs.length,preview_journals:preview.journals.length,observed_at:new Date().toISOString(),audit:preview.audit});
 await page.screenshot({path:root+'/desktop-review.png'});
 await page.focus('#lm-consent');await page.press('#lm-consent','Space');await page.press('#lm-consent','Tab');
 assert(await page.evaluate(()=>document.activeElement.id==='lm-start'),'Keyboard Start flow failed');
 await fs.writeFile(root+'/browser-start-intent.json',JSON.stringify({authorization:'ONE local pretrained browser integration reproduction',at:new Date().toISOString(),reviewed_spec_sha256:'3a49a9cd1b743ba8935582e1e22673bf402d80e68a6136e559dd75fdf73aa08d'})+'\n',{flag:'wx',mode:0o600});
 await page.press('#lm-start','Enter');
 await page.waitForSelector('#lm-job',{state:'visible'});
 await page.screenshot({path:root+'/desktop-running.png'});
 console.log('ONE explicit keyboard Start admitted; natural termination only.');
}
if (initial.jobs.length===1) {
 await page.waitForSelector('#lm-history button');await page.click('#lm-history button');
}
let snapshot=await state();assert(snapshot.jobs.length===1,'Expected exactly one admission');
const jobId=snapshot.jobs[0].id;
await record('admission.json',{job:snapshot.jobs[0],binding:snapshot.bindings[0],at:new Date().toISOString()});
// One bounded observation wait per invocation. A timeout never triggers Start again.
await page.waitForFunction(()=>!document.querySelector('#lm-result').hidden,undefined,{timeout:60000});
const response=await get('/api/v1/lm/jobs/'+jobId+'/result');
assert(terminal(response.job),'Job is not terminal');
await record('service-result.json',response);
await page.evaluate(()=>document.querySelector('#lm-result').scrollIntoView());
await page.screenshot({path:root+'/desktop-result.png'});
const ui=await page.evaluate(()=>({verdict:document.querySelector('#lm-verdict').textContent,reason:document.querySelector('#lm-result-reason').textContent,deltaHidden:document.querySelector('#lm-delta').hidden,counts:document.querySelector('#lm-counts').textContent,overflow:document.documentElement.scrollWidth>innerWidth}));
assert(!ui.overflow,'Desktop result overflow');
assert(ui.deltaHidden===!response.job.selected_delta_available,'False selected delta availability');
assert(ui.reason.includes(response.attempts.filter(a=>a.split==='dev').length+' development attempts'),'Development count mismatch');
assert(ui.reason.includes(response.attempts.filter(a=>a.split==='heldout').length+' heldout attempts'),'Heldout count mismatch');
const selected=response.attempts.find(a=>a.variant==='decoding'&&a.status==='budget_limited') || response.attempts.find(a=>a.variant==='weight-0');
assert(selected,'No candidate response to inspect');
await page.selectOption('#lm-split',selected.split);await page.selectOption('#lm-variant',selected.variant);await page.selectOption('#lm-case',selected.case_id);
const pair=await page.evaluate(()=>({original:document.querySelector('#lm-original').textContent,candidate:document.querySelector('#lm-candidate').textContent,originalScore:document.querySelector('#lm-original-score').textContent,candidateScore:document.querySelector('#lm-candidate-score').textContent}));
const original=response.attempts.find(a=>a.variant==='unchanged'&&a.case_id===selected.case_id&&a.split===selected.split);
assert(pair.original===original.output&&pair.candidate===selected.output,'UI output differs from actual service evidence');
assert(pair.originalScore.includes('schema-valid')&&pair.candidateScore.includes('semantically correct'),'Distinct metrics missing');
await record('ui-comparison.json',{ui,case_id:selected.case_id,variant:selected.variant,pair});
await page.evaluate(()=>document.querySelector('.lm-output-pair').scrollIntoView());await page.screenshot({path:root+'/desktop-responses.png'});
const promise=page.waitForEvent('download');await page.click('#lm-evidence');const download=await promise;await download.saveAs(root+'/downloaded-evidence.json');
const attachment=JSON.parse(await fs.readFile(root+'/downloaded-evidence.json','utf8'));
assert(isDeepStrictEqual(attachment,response),'Evidence attachment differs from service result');
const binding=(await state()).bindings[0];
const resolved=await page.fetch(base+'/api/v1/lm/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({schema_version:1,spec_sha256:binding.spec_sha256,idempotency_key:binding.idempotency_key})});
assert(resolved.ok&&JSON.parse(resolved.body).job.id===jobId,'Read-only resolve identity mismatch');
await page.reload();await page.waitForSelector('#lm-result',{state:'visible'});
await page.click('#lm-history-refresh');await page.waitForSelector('#lm-history button');await page.click('#lm-history button');await page.waitForSelector('#lm-result',{state:'visible'});
assert((await state()).jobs.length===1,'Reload/history created another job');
await page.cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
await page.evaluate(()=>window.scrollTo(0,0));assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile workspace overflow');await page.screenshot({path:root+'/mobile-workspace.png'});
await page.evaluate(()=>document.querySelector('#lm-result').scrollIntoView());assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile result overflow');await page.screenshot({path:root+'/mobile-result.png'});
await page.selectOption('#lm-variant',selected.variant);await page.selectOption('#lm-case',selected.case_id);await page.evaluate(()=>document.querySelector('.lm-output-pair').scrollIntoView());await page.screenshot({path:root+'/mobile-responses.png'});
await page.cdp('Emulation.clearDeviceMetricsOverride');
const apiBefore=(await state()).audit.length;
await page.goto(base+'/recorded/lab.html?goalMode=mock&lmMode=mock#language-model');await page.waitForFunction(()=>document.querySelector('#lm-notice').textContent.includes('static export'));
assert(await page.evaluate(()=>performance.getEntriesByType('resource').every(r=>!new URL(r.name).pathname.startsWith('/api/'))),'Static export called an API');
assert((await state()).audit.length===apiBefore,'Static export audit changed');
await page.screenshot({path:root+'/static-local-only.png'});
snapshot=await state();
const starts=snapshot.audit.filter(c=>c.path==='/api/v1/lm/jobs'&&c.method==='POST');
assert(starts.length===1&&snapshot.jobs.length===1,'More than one real Start');
assert(!snapshot.audit.some(c=>c.path.endsWith('/cancel')),'Real cancellation was not authorized for this reproduction');
await record('browser-verification.json',{purpose:'Actual pretrained transport reproduction, not independent quality evidence',verified_at:new Date().toISOString(),job_id:jobId,job:response.job,attempt_count:response.attempts.length,dev:response.attempts.filter(a=>a.split==='dev').length,heldout:response.attempts.filter(a=>a.split==='heldout').length,status_counts:Object.fromEntries([...new Set(response.attempts.map(a=>a.status))].map(s=>[s,response.attempts.filter(a=>a.status===s).length])),verdict:response.report?.verdict,evidence_attachment_sha256:createHash('sha256').update(await fs.readFile(root+'/downloaded-evidence.json')).digest('hex'),attachment_exact_equality:true,original_candidate_text_equality:true,explicit_keyboard_start:true,desktop_mobile_390_no_overflow:true,preview_zero_jobs:true,static_zero_api:true,start_posts:starts.length,read_only_resolution:true,reload_history_one_job:true,audit:snapshot.audit,journals:snapshot.journals});
console.log({result:'PASS actual service/browser integration',job:response.job,attempts:response.attempts.length,verdict:response.report?.verdict,evidence:root});
// Keep the task open until screenshots are visually inspected in the next round.
