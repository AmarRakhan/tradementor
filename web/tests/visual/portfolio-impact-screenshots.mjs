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

  const imageSize = await page.evaluate(() => new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight });
    image.onerror = () => reject(new Error('portfolio-impact-bulls.webp failed to decode'));
    image.src = `/portfolio-impact-bulls.webp?v=4&qa=${Date.now()}`;
  }));
  assert.ok(imageSize.width >= 500 && imageSize.height >= 140, `${name}: bull artwork decoded at unexpected ${imageSize.width}x${imageSize.height}`);

  // Let the QA fixture produce two live P&L updates; a non-zero pressure state must then be visible.
  await page.waitForTimeout(1100);
  const card = page.locator('section[aria-label^="Portfolio impact."]');
  await card.waitFor({ state: 'visible' });
  const box = await card.boundingBox();
  assert.ok(box && box.width <= width, `${name}: card exceeds viewport width`);
  const ratio = box ? box.width / box.height : 0;
  assert.ok(box && box.height >= 195 && box.height <= 290, `${name}: card height ${box?.height ?? 'n/a'}px outside approved cinematic mobile target`);
  assert.ok(ratio >= 1.45 && ratio <= 1.90, `${name}: card ratio ${ratio.toFixed(2)} outside approved cinematic target`);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  assert.ok(overflow <= 0, `${name}: horizontal overflow ${overflow}px`);

  const text = await card.innerText();
  assert.match(text, /SHORTS DRUKKEN HARDER/, `${name}: live-pressure fixture stayed balanced instead of reacting to short momentum`);
  assert.doesNotMatch(text, /50%\s+50%/, `${name}: live-pressure bar remained stuck at 50/50`);
  const computedArt = await page.locator('section[aria-label^="Portfolio impact."] > div').first().evaluate((element) => getComputedStyle(element).backgroundImage);
  assert.match(computedArt, /portfolio-impact-bulls\.webp/, `${name}: production bull artwork is not the verified WebP`);

  await card.screenshot({ path: `artifacts/portfolio-impact/${name}.png` });
  await browser.close();
}
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' });
await page.goto(url, { waitUntil: 'networkidle' });
await page.waitForTimeout(1100);
const reducedCard = page.locator('section[aria-label^="Portfolio impact."]');
await reducedCard.waitFor({ state: 'visible' });
const reducedBox = await reducedCard.boundingBox();
assert.ok(reducedBox && reducedBox.height >= 195 && reducedBox.height <= 290, 'reduced-motion-390: cinematic card geometry regressed');
assert.match(await reducedCard.innerText(), /SHORTS DRUKKEN HARDER/, 'reduced-motion-390: live pressure must remain data-driven when animation is disabled');
await reducedCard.screenshot({ path: 'artifacts/portfolio-impact/reduced-motion-390.png' });
await browser.close();
console.log('Portfolio Impact visual QA screenshots and live-pressure assertions complete');
