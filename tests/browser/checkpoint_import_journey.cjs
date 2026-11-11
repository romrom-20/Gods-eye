// Real production UI + real import handler. Only the temporary fixture on 18992.
const assert = (v,m) => {if (!v) throw Error(m);};
const task = await taskSpace('Local checkpoint import acceptance');
const page = task.page('p1'), base = 'http://127.0.0.1:18992';
const fixture = () => fetch(base+'/__fixture/state').then(r=>r.json());
const initial = await fixture();
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
await page.screenshot({path:'/tmp/godseye-import-success.png'});
await page.click('#import-compare');
assert(await page.evaluate(() => location.hash === '#evaluate'),'compare action unavailable');
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
console.log('PASS real import, unchanged paper/zero choices, source markup safety, root inspect/patch/compare, lost acknowledgment and explicit read-only reconciliation');
await task.finish({keep:[]});
