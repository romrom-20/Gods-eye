// Real production UI + real import handler. Only the temporary fixture on 18992.
const assert = (v,m) => {if (!v) throw Error(m);};
const task = await taskSpace('Local checkpoint import acceptance');
const page = task.page('p1'), base = 'http://127.0.0.1:18992';
const fixture = () => fetch(base+'/__fixture/state').then(r=>r.json());
const initial = await fixture();
console.log({spaceId:task.spaceId});
const capability = await (await fetch(base+'/api/v1/state')).json();
assert(capability.mode === 'local' && capability.backend === 'minatar-breakout-v1' && capability.capabilities.includes('checkpoint_import'),'live import capability missing');
await page.goto(base+'/lab#workbench');
await page.waitForFunction(() => !document.getElementById('import-open').disabled);
console.log(await page.snapshot({scope:'full_page'}));
await page.click('#import-open');
await page.click('#import-submit');
assert(await page.evaluate(() => document.activeElement.id === 'import-file'),'missing-file error did not focus picker');
const injection = '<img src=x onerror="globalThis.importInjected=true">';
await page.setInputFiles('#import-file',[initial.file]);
await page.fill('#import-name', 'Browser imported original');
await page.fill('#import-provenance', injection);
assert((await fixture()).writes === 0,'file selection imported without explicit submit');
await page.click('#import-submit');
await page.waitForFunction(() => document.getElementById('import-status').textContent.includes('Imported original saved'));
const success = await fixture();
assert(success.writes === 1 && success.original_preserved,'expected one write and unchanged paper');
assert(await page.evaluate(text => {
  const $ = id => document.getElementById(id), selected = $('inspect-model').value;
  return selected !== 'paper' && selected === $('patch-base').value && selected === $('base').value &&
    $('candidate').value === 'paper' && $('import-metadata').textContent.includes(text) &&
    $('import-metadata').querySelector('img') === null && !globalThis.importInjected &&
    [...$('inspect-model').options].some(x=>x.value==='paper') && [...$('inspect-model').options].some(x=>x.value==='zero');
},injection),'import root selection, bundled preservation or inert metadata failed');
const imported = success.checkpoints.find(c=>c.name === 'Browser imported original');
assert(imported.parent === null && !('patch' in imported) && !('diff' in imported) && imported.source_sha256 === initial.source_sha256 && imported.provenance === injection,'raw NPZ top-level metadata mismatch');
assert(success.hashes[imported.id] === initial.hashes.paper,'import changed tensors');
await page.screenshot({path:'/tmp/godseye-import-success.png'});
await page.click('#import-compare');
assert(await page.evaluate(() => location.hash === '#evaluate'),'compare action unavailable');
// Edit a copy of the imported original and run the ordinary bounded CPU job.
await page.click('[data-nav="workbench"]');
await page.fill('#patch', 'W3[0:8:2, 1] = 0');
await page.fill('#hypothesis', 'Browser bounded edit from imported root');
await page.click('#apply');
await page.waitForFunction(() => document.getElementById('patch-result').textContent.includes('created.'));
const edited = (await fixture()).checkpoints.find(c=>c.parent === imported.id);
assert(edited && edited.sha256 !== imported.sha256,'edit did not create a changed child');
await page.click('#compare-patch');
await page.click('.comparison-options > summary');
await page.fill('#episodes', '2');
await page.fill('#max-steps', '100');
assert(await page.evaluate(ids => document.getElementById('base').value === ids[0] && document.getElementById('candidate').value === ids[1],[imported.id,edited.id]),'comparison does not use imported original and child');
await page.click('#evaluate');
await page.waitForFunction(() => document.getElementById('eval-status').textContent.includes('Evaluation completed and saved.'),undefined,{timeout:45000});
const measured = await fixture(), run = measured.runs.find(r=>r.base_id===imported.id && r.candidate_id===edited.id);
assert(run && run.episodes === 2 && run.max_steps === 100 && run.base.forward_calls <= 200 && run.candidate.forward_calls <= 200,'missing actual bounded persisted CPU comparison');
assert(measured.hashes[imported.id] === imported.sha256 && measured.original_preserved,'editing/evaluation changed an original');
await page.click('[data-nav="overview"]');
await page.waitForSelector('#results',{state:'visible'});
await page.screenshot({path:'/tmp/godseye-import-cpu-result.png'});
await page.goto(base+'/lab#workbench');
await page.waitForFunction(id => [...document.getElementById('inspect-model').options].some(x=>x.value===id),imported.id);
await page.selectOption('#inspect-model', imported.id);
await page.waitForFunction(hash => document.getElementById('hash').textContent.includes(hash),imported.sha256);
assert(await page.evaluate(hash=>document.getElementById('import-metadata').textContent.includes(hash),initial.source_sha256),'source metadata missing after reload');
const reloaded = await fixture();
assert(reloaded.hashes[imported.id] === imported.sha256 && reloaded.hashes.paper === initial.hashes.paper && reloaded.runs.some(r=>r.id===run.id),'disk reload did not preserve original, paper, or run');
console.log({imported:imported.id,edited:edited.id,run:run.id,episodes:run.episodes,max_steps:run.max_steps,forward_calls:[run.base.forward_calls,run.candidate.forward_calls]});
// Real second import, followed by a deliberately lost acknowledgment.
await page.goto(base+'/lab#workbench');
await page.waitForFunction(() => !document.getElementById('import-open').disabled);
await page.click('#import-open');
await page.setInputFiles('#import-file',[initial.file]);
await page.fill('#import-name','Acknowledgment lost');
await fetch(base+'/__fixture/drop-ack',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({drop:true})});
await page.click('#import-submit');
await page.waitForFunction(() => document.getElementById('import-status').textContent.includes('outcome is unknown'));
assert(await page.evaluate(() => document.getElementById('import-submit').disabled),'uncertain write may be resubmitted immediately');
await page.click('#import-refresh');
await page.waitForFunction(() => document.getElementById('import-status').textContent.includes('Saved versions refreshed'));
const reconciled = await fixture();
assert(reconciled.writes === 2 && reconciled.original_preserved,'reconciliation retried an import or changed paper');
assert(await page.evaluate(() => [...document.getElementById('inspect-model').options].some(x=>x.textContent.includes('Acknowledgment lost'))),'saved import not discoverable after lost acknowledgment');
// Exported static demo uses the exact merged UI and never contacts /api/.
await page.goto(base+'/recorded/lab.html#workbench');
await page.waitForFunction(() => document.getElementById('import-support').textContent.includes('read-only'));
assert(await page.evaluate(async () => {
  const $=id=>document.getElementById(id);
  await submitImport({preventDefault(){}});
  let refused=false; try { await api('/api/v1/checkpoints/import',{}); } catch (_) { refused=true; }
  return refused && $('import-open').hidden && $('import-sidebar').hidden && $('import-submit').disabled &&
    performance.getEntriesByType('resource').every(r=>!new URL(r.name).pathname.startsWith('/api/'));
}),'static demo attempted API access or allowed import');
assert((await fixture()).writes === 2,'static navigation or reconciliation issued another import');
console.log('PASS real import/edit/bounded CPU comparison/disk+browser reload, unchanged originals, top-level source metadata, lost acknowledgment reconciliation with no automatic duplicate writes, exact exported static UI without API requests');
await task.finish({keep:[]});
