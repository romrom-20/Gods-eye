// Only tests/browser/first_use_backend.py; an unconfigured temporary lab.
const assert = (v,m) => {if (!v) throw Error(m);};
const task = await taskSpace('Bounded first-use browser journey');
const page = task.page('p1'), base = 'http://127.0.0.1:18980';
await page.goto(base+'/lab');
await page.waitForFunction(() => !document.getElementById('quick-experiment').disabled);
console.log(await page.snapshot());
assert(await page.evaluate(() => document.getElementById('goal-guided').getBoundingClientRect().height >= 44),'no-key action unavailable');
await page.screenshot({path:'/tmp/godseye-first-use-request.png'});
await page.click('#goal-guided');
await page.click('#quick-experiment');
await page.waitForFunction(() => document.getElementById('eval-status').textContent.includes('Evaluation completed and saved.'),undefined,{timeout:45000});
const preserved = await (await fetch(base+'/__fixture/state')).json();
assert(preserved.original_preserved,'no-key example modified original');
assert(await page.evaluate(() => document.getElementById('episodes').value === '4' && document.getElementById('max-steps').value === '1000'),'example not bounded');
await page.goto(base+'/lab#overview');
await page.waitForSelector('#results',{state:'visible'});
await page.screenshot({path:'/tmp/godseye-first-use-cpu-result.png'});
console.log('PASS real unconfigured no-key CPU example, bounded four games, persisted result, unchanged original');
// Keep this single space for the scripted-goal journey next.
