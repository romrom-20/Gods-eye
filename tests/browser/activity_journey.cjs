// Run against tests/browser/activity_backend.py only. No operator service.
const assert=(v,m)=>{if(!v)throw Error(m);};
const task=await taskSpace('Integrated activity and checkpoint export');
console.log({spaceId:task.spaceId});
const page=task.page('p1'),base='http://127.0.0.1:8881';
const post=async(path,body)=>{const r=await fetch(base+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});assert(r.ok,'fixture request failed');return r.json();};
const text=id=>page.evaluate(id=>document.getElementById(id).textContent,id);
const waitText=(id,value)=>page.waitForFunction(({id,value})=>document.getElementById(id).textContent.includes(value),{id,value},{timeout:20000});
await page.goto(base+'/lab?activity-test=1');
await waitText('goal-notice','Live experiment');
console.log(await page.snapshot());
await page.fill('#goal-draft','Improve Breakout score');
await page.evaluate(()=>document.getElementById('goal-advanced').open=true);
await page.fill('#goal-model','scripted-acceptance');
await page.evaluate(()=>{for(const [id,value] of Object.entries({requests:40,rounds:40,calls:80,seconds:30,reply:100,tokens:10000})){const input=document.getElementById('goal-'+id);input.value=String(value);input.dispatchEvent(new Event('input',{bubbles:true}));}});
await page.click('#goal-plan');
await page.waitForSelector('#goal-review',{state:'visible'});
await page.click('#goal-consent');await page.click('#goal-start');
await waitText('goal-result-title','completed');
await page.click('#goal-activity summary');
for(let i=0;i<20;i++){
  const more=await page.evaluate(()=>!document.getElementById('goal-activity-more').hidden);
  if(!more)break;
  const before=await text('goal-activity-events');
  await page.click('#goal-activity-more');
  await page.waitForFunction(before=>document.getElementById('goal-activity-events').textContent!==before,before);
}
await waitText('goal-activity-events','Worker finished');
const history=await text('goal-activity-events');
assert(history.includes('Original policy probe reserved'),'no real original probe');
assert(history.includes('Selection frozen'),'no actual freeze');
assert(history.includes('Held-out rollout reserved after all selections froze'),'no actual held-out reservation');
assert(history.indexOf('Selection frozen')<history.indexOf('Held-out rollout reserved'),'reveal before freeze');
assert((await text('goal-phase')).includes('Activity unavailable'),'terminal phase did not reset');
const before=await(await fetch(base+'/__fixture/state')).json();
await page.goto(base+'/lab?activity-test=reload');
await waitText('goal-result-title','completed');
const after=await(await fetch(base+'/__fixture/state')).json();
assert(before.workers===after.workers,'reload launched worker');
assert(before.key_reads===after.key_reads,'reload read key');
const saved=await page.evaluate(()=>JSON.parse(sessionStorage.getItem('godseye.goal-live.v1')));
const expected=await post('/__fixture/checkpoint-hashes',{experiment_id:saved.run.experiment_id});
await post('/__fixture/export-mode',{ok:false,experiment_id:saved.run.experiment_id});
await page.click('#goal-download');
await waitText('goal-download-status','Download unavailable:');
await post('/__fixture/export-mode',{ok:true,experiment_id:saved.run.experiment_id});
const downloadPromise=page.waitForEvent('download',{timeout:20000});
await page.click('#goal-download');
const download=await downloadPromise;
const path='/tmp/godseye-activity-download-'+saved.run.experiment_id+'.json';await download.saveAs(path);
const fs=await import('node:fs/promises');
const artifact=JSON.parse(await fs.readFile(path,'utf8'));
assert(artifact.format==='godseye-checkpoint-v1','not the production export format');
assert(artifact.experiment_id===saved.run.experiment_id,'download scope differs');
const {execFile}=await import('node:child_process');
const validation=await new Promise((resolve,reject)=>execFile(expected.python_executable,['-I','-c',`
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from godseye.checkpoint_artifact import reload_artifact
from godseye.core import digest
pairs=reload_artifact(Path(sys.argv[2]).read_bytes(),expected_sha256=sys.argv[3])
print(json.dumps([[digest(original),digest(selected)] for original,selected in pairs]))
`,expected.source_root,path,artifact.content_sha256],{timeout:20000},(error,stdout,stderr)=>error?reject(Error(stderr||error.message)):resolve(JSON.parse(stdout))));
assert(JSON.stringify(validation)===JSON.stringify(expected.hashes),'independent reload differs from private original/selected hashes');
assert(JSON.stringify(validation)===JSON.stringify(artifact.checkpoints.map(c=>[c.original_sha256,c.selected_sha256])),'declared checkpoint hashes differ');
await fs.unlink(path);
await waitText('goal-download-status','Checkpoint download requested');
const downloadedState=await(await fetch(base+'/__fixture/state')).json();
assert(downloadedState.workers===after.workers && downloadedState.key_reads===after.key_reads,'download launched work or read credentials');
await post('/__fixture/activity-gap',{experiment_id:saved.run.experiment_id});
await page.click('#goal-reconnect');await waitText('goal-activity-notice','Activity unavailable');
assert((await text('goal-phase')).includes('Activity unavailable'),'gap advertised a phase');
console.log({result:'passed',reloadWorkers:after.workers,observedHistory:history.length,download:'real export independently reloaded',checkpoints:validation.length});
console.log(await page.snapshot());
await task.finish({keep:[]});
