// Export beneath /Gods-eye/ and serve its parent on 127.0.0.1:8894.
// Run: ego-browser nodejs < tests/browser/api_guide_journey.cjs
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const task = await taskSpace('Gods Eye developer guide');
const page = task.page('p1');
const base = 'http://127.0.0.1:8894/Gods-eye/';
await page.goto(base + 'api.html');
console.log(await page.snapshot());
for (const width of [1440, 390, 320]) {
  await page.cdp('Emulation.setDeviceMetricsOverride', {width, height:900, deviceScaleFactor:1, mobile:width<681});
  const layout = await page.evaluate(() => ({
    width:innerWidth, scroll:document.documentElement.scrollWidth,
    main:document.querySelector('main').getBoundingClientRect().width,
    h1:parseFloat(getComputedStyle(document.querySelector('h1')).fontSize),
    body:parseFloat(getComputedStyle(document.body).fontSize),
    pre:[...document.querySelectorAll('pre')].every(p => p.getBoundingClientRect().right <= innerWidth),
    sidebar:getComputedStyle(document.querySelector('.sidebar')).position,
  }));
  assert(layout.width === layout.scroll, `Document overflow ${width}`);
  assert(layout.main <= 760 && layout.main <= width-40, `Unbounded reading column ${width}`);
  assert(layout.h1 <= 58 && layout.body === 15, `Type-scale regression ${width}`);
  assert(layout.pre, `Code escaped column ${width}`);
  assert(layout.sidebar === (width>680?'sticky':'static'), `Contents position ${width}`);
}
await page.focus('.contents summary');
await page.keyboard.press('Enter');
assert(await page.evaluate(() => !document.querySelector('.contents').open), 'Contents did not close by keyboard');
await page.keyboard.press('Enter');
assert(await page.evaluate(() => document.querySelector('.contents').open), 'Contents did not reopen');
await page.focus('nav[aria-label="Contents"] a[href="#http"]');
await page.keyboard.press('Enter');
await page.waitForURL('**/api.html#http');
assert(await page.evaluate(() => Math.abs(document.getElementById('http').getBoundingClientRect().top-24)<3), 'HTTP anchor scroll');
const summaries = '.endpoints details:nth-child(2) summary';
await page.focus(summaries);
await page.keyboard.press('Enter');
assert(await page.evaluate(() => document.querySelector('.endpoints details:nth-child(2)').open), 'Endpoint keyboard expansion');
const endpointPre = '.endpoints details:nth-child(2) pre';
await page.focus(endpointPre);
await page.keyboard.press('ArrowRight');
await page.waitForFunction(() => document.querySelector('.endpoints details:nth-child(2) pre').scrollLeft > 0);
await page.focus('#agent-brief');
await page.keyboard.press('ControlOrMeta+A');
assert(await page.evaluate(() => {
  const e=document.getElementById('agent-brief');
  return e.readOnly && e.selectionStart === 0 && e.selectionEnd === e.value.length;
}), 'Agent brief cannot be selected for copying');
const anchors = await page.evaluate(() => [...document.querySelectorAll('nav[aria-label="Contents"] a')].map(a=>a.hash));
for (const hash of anchors) {
  await page.click(`nav[aria-label="Contents"] a[href="${hash}"]`);
  assert(await page.evaluate(id => Boolean(document.querySelector(id)), hash), `Missing anchor ${hash}`);
}
const requests = await page.evaluate(() => performance.getEntriesByType('resource').map(r=>r.name));
assert(requests.length === 0, 'Guide depends on external resources or API calls');
await page.goto(base);
assert(await page.evaluate(() => getComputedStyle(document.querySelector('h1')).fontFamily.includes('Georgia')), 'Landing typography changed');
assert(await page.evaluate(() => document.querySelector('#board-base rect') && !document.getElementById('scrubber').hidden), 'Landing evidence regression');
await page.click('.site-footer a[href="api.html"]');
await page.waitForURL('**/api.html');
assert(await page.evaluate(() => document.body.className === 'guide' && parseFloat(getComputedStyle(document.querySelector('h1')).fontSize) <= 58), 'Landing to guide navigation regression');
console.log('PASS: bounded rendered typography/columns at 320/390/1440, keyboard contents/endpoints/code scroll/brief selection, anchor navigation, zero guide dependencies, landing regression.');
await task.finish({ keep: [] });
