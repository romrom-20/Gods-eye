// Run with ego-browser nodejs < tests/browser/landing_journey.cjs.
// Serve export-demo under /Gods-eye/ on 127.0.0.1:8894 (see website-design.md).
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const task = await taskSpace('Gods Eye website design');
const page = task.page('p1');
const url = 'http://127.0.0.1:8894/Gods-eye/';
await page.goto(url);
await page.cdp('Emulation.setDeviceMetricsOverride', { width:1440, height:1000, deviceScaleFactor:1, mobile:false });
console.log(await page.snapshot());
for (const width of [1440, 1024, 768, 680, 390, 320]) {
  await page.cdp('Emulation.setDeviceMetricsOverride', { width, height:844, deviceScaleFactor:1, mobile:width<681 });
  assert(await page.evaluate(() => document.documentElement.scrollWidth === innerWidth), `Overflow at ${width}`);
}
await page.cdp('Emulation.setEmulatedMedia', { features:[{name:'prefers-reduced-motion',value:'reduce'}] });
assert(await page.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior === 'auto'), 'Reduced motion');
await page.focus('#recorded-frame');
await page.keyboard.press('End');
assert(await page.evaluate(() => document.getElementById('frame-label').textContent === 'step 399 · ablated ended'), 'Keyboard scrub end');
assert(await page.evaluate(() => document.getElementById('board-candidate').getAttribute('aria-label').endsWith('frame 5')), 'Ended episode frozen');
await page.keyboard.press('Home');
assert(await page.evaluate(() => document.getElementById('frame-label').textContent === 'step 0'), 'Keyboard scrub start');
await page.click('#copy-install');
await page.waitForFunction(() => document.getElementById('copy-status').textContent.length > 0);
console.log('Clipboard feedback:', await page.evaluate(() => document.getElementById('copy-status').textContent));
const links = await page.evaluate(() => [...document.querySelectorAll('a')].map(a => a.href));
for (const href of [...new Set(links.filter(h => h.startsWith(url)))]) {
  const target = new URL(href);
  const result = await page.fetch(target.pathname);
  assert(result.status === 200, `Missing local CTA ${href}`);
  if (target.hash && target.pathname === '/Gods-eye/') {
    assert(await page.evaluate(id => Boolean(document.getElementById(id)), target.hash.slice(1)), `Missing anchor ${href}`);
  }
}
const resources = await page.evaluate(() => performance.getEntriesByType('resource').map(r => r.name));
assert(resources.every(r => new URL(r).origin === new URL(url).origin), 'External landing dependency');
assert(resources.every(r => !new URL(r).pathname.startsWith('/api/')), 'Landing API request');
await page.click('a.primary');
await page.waitForURL('**/lab.html#overview');
await page.waitForFunction(() => document.documentElement.dataset.staticDemo === 'true');
assert(await page.evaluate(() => !document.getElementById('goal-form')), 'Live goal form leaked');
const labResources = await page.evaluate(() => performance.getEntriesByType('resource').map(r => r.name));
assert(labResources.every(r => !new URL(r).pathname.includes('/api/')), 'Recorded lab API request');
await page.goto(url);
await page.click('a[href="lab.html#workbench"]');
await page.waitForURL('**/lab.html#workbench');
assert(await page.evaluate(() => document.documentElement.dataset.staticDemo === 'true'), 'Workbench lost recorded mode');
console.log('PASS: six viewport widths, reduced motion, keyboard scrub, copy feedback, local CTAs, recorded overview/workbench, zero external/API dependencies.');
await task.finish({ keep: [] });
