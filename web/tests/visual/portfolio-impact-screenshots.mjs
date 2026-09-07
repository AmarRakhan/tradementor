import { chromium, webkit } from 'playwright';
import { mkdir } from 'node:fs/promises';
import assert from 'node:assert/strict';

await mkdir('artifacts/portfolio-impact', { recursive: true });
const url = 'http://127.0.0.1:4173/tests/visual/portfolio-impact.html';
const cases = [
  ['chromium-360', chromium, 360, 800],
  ['chromium-390', chromium, 390, 844],
  ['chromium-412', chromium, 412, 915],
  ['chromium-430', chromium, 430, 932],
  ['webkit-390', webkit, 390, 844],
];

for (const [name, type, width, height] of cases) {
  const browser = await type.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  await page.goto(url, { waitUntil: 'networkidle' });
  const card = page.locator('section[aria-label^="Portfolio impact."]');
  await card.waitFor({ state: 'visible' });
  const box = await card.boundingBox();
  assert.ok(box && box.width <= width, `${name}: card exceeds viewport width`);
  const ratio = box ? box.width / box.height : 0;
  assert.ok(box && box.height >= 140 && box.height <= 190, `${name}: card height ${box?.height ?? 'n/a'}px outside approved premium banner target`);
  assert.ok(ratio >= 2.20 && ratio <= 2.50, `${name}: card ratio ${ratio.toFixed(2)} outside reference target`);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  assert.ok(overflow <= 0, `${name}: horizontal overflow ${overflow}px`);
  assert.match(await card.innerText(), /SHORTS DRUKKEN HARDER/, `${name}: 15m fixture must show short pressure`);
  const sceneSrc = await card.locator('img').first().getAttribute('src');
  assert.equal(sceneSrc, '/portfolio-impact-premium-clean.webp', `${name}: fixed clean background missing`);
  const firstFrame = Number(await card.getAttribute('data-battle-animation-frame'));
  await page.waitForTimeout(180);
  const laterFrame = Number(await card.getAttribute('data-battle-animation-frame'));
  assert.notEqual(firstFrame, laterFrame, `${name}: battle foreground is not continuously animating`);
  assert.ok(Number(await card.getAttribute('data-battle-intensity')) > 0.28, `${name}: short pressure should raise battle intensity`);
  await card.screenshot({ path: `artifacts/portfolio-impact/${name}.png` });
  await browser.close();
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' });
await page.goto(url, { waitUntil: 'networkidle' });
const card = page.locator('section[aria-label^="Portfolio impact."]');
await card.waitFor({ state: 'visible' });
for (const [label, expected] of [
  ['1m', 'SHORTS DOMINEREN'],
  ['5m', 'SHORTS DRUKKEN HARDER'],
  ['15m', 'SHORTS DRUKKEN HARDER'],
  ['1u', 'IN EVENWICHT'],
  ['4u', 'LONGS DRUKKEN HARDER'],
  ['24u', 'LONGS DOMINEREN'],
]) {
  await page.getByRole('button', { name: label, exact: true }).click();
  await page.waitForTimeout(80);
  assert.match(await card.innerText(), new RegExp(expected), `${label}: expected ${expected}`);
  if (label === '1m') await card.screenshot({ path: 'artifacts/portfolio-impact/extreme-short-390.png' });
  if (label === '1u') await card.screenshot({ path: 'artifacts/portfolio-impact/balance-390.png' });
  if (label === '24u') await card.screenshot({ path: 'artifacts/portfolio-impact/extreme-long-390.png' });
}
const reducedBox = await card.boundingBox();
assert.ok(reducedBox && reducedBox.height >= 140 && reducedBox.height <= 190, 'reduced-motion-390: reference card geometry regressed');
await card.screenshot({ path: 'artifacts/portfolio-impact/reduced-motion-390.png' });
await browser.close();
console.log('Portfolio Impact film-battle visual QA complete');
