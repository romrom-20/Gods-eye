// ego-browser nodejs < tests/browser/lm_history_transition_journey.cjs
// Actual GET routes over a private copy of retained history; no inference runtime.
const fs=await import('node:fs/promises');
const assert=(v,m)=>{if(!v)throw Error(m);};
const base='http://127.0.0.1:18998';
const task=await taskSpace('Qwen history and board transitions'),page=task.page('p1');
const latest='4539b260-9794-4184-b959-f10b1c5c8864';
const get=async path=>(await fetch(base+path)).json();
const frame=()=>page.evaluate(()=>({scale:Number(document.querySelector('#board-graph').style.transform.match(/scale\(([^)]+)/)?.[1]),width:document.querySelector('#board-viewport').clientWidth,nodes:[...document.querySelectorAll('.experiment-node')].map(n=>({id:n.dataset.objectId,width:n.getBoundingClientRect().width,x:n.getBoundingClientRect().x})),overflow:document.documentElement.scrollWidth>innerWidth}));
const evidence=[];
await page.goto(base+'/lab#language-model');await page.reload();await page.waitForSelector('#lm-history button');
assert(await page.evaluate(()=>document.querySelector('#lm-history-count').textContent==='2'),'Qwen jobs absent from nav count');
await page.click('[data-nav="workbench"]');let board=await frame();assert(board.scale>0&&board.nodes.length===2&&board.nodes.every(n=>n.width>100),'Qwen->Breakout board empty or unreadable');
assert(await page.evaluate(()=>document.querySelector('.workbench-intro').textContent.includes('no manual Qwen editor')),'Manual editor target unclear');
evidence.push({desktop_board:board});await page.waitForFunction(()=>document.querySelector('[data-view="workbench"]').getAnimations({subtree:true}).every(a=>a.playState!=='running'));await page.screenshot({path:'/tmp/qwen-transition-desktop-fixed.png'});
// Fit/Reset remain safe after a hidden start and a bounded but distant saved layout.
await page.evaluate(()=>localStorage.setItem('godseye.board-layout.v1:local:/',JSON.stringify({version:1,positions:{paper:{x:5000,y:5000},zero:{x:5500,y:5200}}})));
await page.goto(base+'/lab#language-model');await page.waitForSelector('#lm-history button');await page.click('[data-nav="workbench"]');await page.click('#board-fit');
board=await frame();assert(board.scale>0&&board.nodes.length===2,'Stored-layout Fit invalid');
await page.click('#board-reset');board=await frame();assert(board.nodes.every(n=>n.width>100),'Reset did not restore readable cards');
await page.click('#lm-history-nav');assert(await page.evaluate(()=>document.activeElement.id==='lm-history-title'&&document.querySelector('#lm-workspace').hidden===false),'Qwen history nav not reachable/focused');
await page.click('#lm-history button:has-text("'+latest+'")');await page.waitForSelector('#lm-result',{state:'visible'});
assert(await page.evaluate(()=>document.querySelector('#lm-job-title').textContent.startsWith('Budget stopped')&&document.querySelector('#lm-notice').textContent.includes('Budget stopped')),'Generic failure instead of budget reason');
assert(await page.evaluate(()=>document.querySelector('#lm-result-reason').textContent.includes('70 development attempts · 0 heldout')&&document.querySelector('#lm-delta').hidden),'Retained budget evidence incorrect');
await page.click('#lm-view-evidence');assert(await page.evaluate(()=>document.activeElement.id==='lm-verdict'),'Retained-evidence shortcut does not focus result');
await page.screenshot({path:'/tmp/qwen-history-desktop-result.png'});
await page.selectOption('#lm-variant','decoding');await page.selectOption('#lm-case','dev-inventory');
const actual=await get('/api/v1/lm/jobs/'+latest+'/result');
assert(await page.evaluate(output=>document.querySelector('#lm-candidate').textContent===output,actual.attempts.find(a=>a.attempt_id==='dev-decoding-3').output),'Retained response changed');
await page.cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
await page.goto(base+'/lab#language-model');await page.waitForSelector('#lm-history button');await page.click('[data-nav="workbench"]');board=await frame();
assert(board.scale>0&&!board.overflow&&board.nodes.every(n=>n.width>60),'Mobile route transition board broken');evidence.push({mobile_board:board});
await page.screenshot({path:'/tmp/qwen-transition-mobile-fixed.png'});
await page.click('#board-list-toggle');await page.click('#board-fit');await page.click('#board-list-toggle');assert((await frame()).scale>0,'List/Fit corrupted zoom');
await page.click('#lm-history-nav');await page.click('#lm-history button:has-text("'+latest+'")');await page.waitForSelector('#lm-result',{state:'visible'});
assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile retained history overflow');await page.screenshot({path:'/tmp/qwen-history-mobile-result.png'});
await page.cdp('Emulation.clearDeviceMetricsOverride');
const before=(await get('/__fixture/state')).audit.length;
await page.goto(base+'/recorded/lab.html?goalMode=mock#language-model');await page.waitForFunction(()=>document.querySelector('#lm-notice').textContent.includes('static export'));
await page.click('#lm-history-nav');await page.click('[data-nav="workbench"]');assert((await frame()).scale>0,'Static Qwen transition board broken');
assert(await page.evaluate(()=>performance.getEntriesByType('resource').every(r=>!new URL(r.name).pathname.startsWith('/api/'))),'Static history/nav called API');
const state=await get('/__fixture/state');assert(state.audit.length===before,'Static export changed API audit');
assert(state.jobs.length===2&&state.audit.every(r=>r.method==='GET'),'Unexpected mutation or history loss');
await fs.writeFile('/tmp/qwen-history-transition-evidence.json',JSON.stringify({purpose:'Read-only copied retained history; zero inference',latest_job:latest,checks:evidence,api_methods:[...new Set(state.audit.map(r=>r.method))],retained_jobs:state.jobs,static_zero_api:true,history_exact_response_equality:true},null,2)+'\n');
console.log('PASS desktop/mobile Qwen->Breakout, positive Fit, stored layout Reset, List/Fit, Qwen history count2 and retained budget evidence, exact capped output, zero mutations/inference, static zero API.');
// Finish after screenshots have been visually inspected.
