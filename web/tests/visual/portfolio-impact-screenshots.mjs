import { chromium, webkit } from 'playwright';
import { mkdir } from 'node:fs/promises';
import assert from 'node:assert/strict';

await mkdir('artifacts/portfolio-impact', { recursive: true });
const url = 'http://127.0.0.1:4173/tests/visual/portfolio-impact.html';

async function waitForSettled(page) {
  await page.waitForFunction(() => {
    const card = document.querySelector('section[aria-label^="Portfolio impact."]');
    return card && card.getAttribute('data-frame-index') === card.getAttribute('data-target-frame-index');
  }, null, { timeout: 8000 });
}

async function qaClick(page, selector) {
  await page.evaluate((target) => {
    const button = document.querySelector(target);
    if (!(button instanceof HTMLButtonElement)) throw new Error(`Missing QA button ${target}`);
    button.click();
  }, selector);
}

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
  await waitForSettled(page);
  const box = await card.boundingBox();
  assert.ok(box && box.width <= width, `${name}: card exceeds viewport width`);
  const ratio = box ? box.width / box.height : 0;
  assert.ok(box && box.height >= 130 && box.height <= 180, `${name}: card height ${box?.height ?? 'n/a'}px outside approved 900x363 mobile composition`);
  assert.ok(ratio >= 2.42 && ratio <= 2.54, `${name}: card ratio ${ratio.toFixed(2)} must match approved 900x363 reference`);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  assert.ok(overflow <= 0, `${name}: horizontal overflow ${overflow}px`);
  assert.match(await card.innerText(), /SHORTS DRUKKEN HARDER/, `${name}: 15m fixture must show short pressure`);
  const sceneSrc = await card.locator('img').first().getAttribute('src');
  assert.match(sceneSrc || '', /portfolio-impact-frames\/frame-\d{3}\.svg/, `${name}: half-percent frame asset missing`);
  const centerBackground = await card.locator('div').filter({ hasText: 'PORTFOLIO IMPACT' }).first().evaluate((node) => getComputedStyle(node).backgroundColor);
  assert.ok(centerBackground === 'rgba(0, 0, 0, 0)' || centerBackground === 'transparent', `${name}: center P&L must not be an opaque pasted block`);
  await card.screenshot({ path: `artifacts/portfolio-impact/${name}.png` });
  await browser.close();
}

const reducedBrowser = await chromium.launch({ headless: true });
const reducedPage = await reducedBrowser.newPage({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' });
await reducedPage.goto(url, { waitUntil: 'networkidle' });
const reducedCard = reducedPage.locator('section[aria-label^="Portfolio impact."]');
await reducedCard.waitFor({ state: 'visible' });
for (const [label, expected] of [
  ['1m', 'SHORTS DOMINEREN'],
  ['5m', 'SHORTS DRUKKEN HARDER'],
  ['15m', 'SHORTS DRUKKEN HARDER'],
  ['1u', 'IN EVENWICHT'],
  ['4u', 'LONGS DRUKKEN HARDER'],
  ['24u', 'LONGS DOMINEREN'],
]) {
  await reducedPage.getByRole('button', { name: label, exact: true }).click();
  await reducedPage.waitForTimeout(40);
  await waitForSettled(reducedPage);
  assert.match(await reducedCard.innerText(), new RegExp(expected), `${label}: expected ${expected}`);
  if (label === '1m') await reducedCard.screenshot({ path: 'artifacts/portfolio-impact/extreme-short-390.png' });
  if (label === '1u') await reducedCard.screenshot({ path: 'artifacts/portfolio-impact/balance-390.png' });
  if (label === '24u') await reducedCard.screenshot({ path: 'artifacts/portfolio-impact/extreme-long-390.png' });
}
await reducedCard.screenshot({ path: 'artifacts/portfolio-impact/reduced-motion-390.png' });
await reducedBrowser.close();

const motionBrowser = await chromium.launch({ headless: true });
const motionPage = await motionBrowser.newPage({ viewport: { width: 390, height: 844 } });
await motionPage.goto(url, { waitUntil: 'networkidle' });
const motionCard = motionPage.locator('section[aria-label^="Portfolio impact."]');
await motionCard.waitFor({ state: 'visible' });
await qaClick(motionPage, '#qa-neutral');
await waitForSettled(motionPage);
assert.equal(await motionCard.getAttribute('data-frame-index'), '100', 'neutral must be frame 100');

async function captureTransition(targetSelector, expectedEnd, direction) {
  await motionPage.evaluate(() => {
    const card = document.querySelector('section[aria-label^="Portfolio impact."]');
    window.__bullFrames = [Number(card?.getAttribute('data-frame-index'))];
    window.__bullObserver?.disconnect?.();
    window.__bullObserver = new MutationObserver(() => {
      const value = Number(card?.getAttribute('data-frame-index'));
      if (Number.isFinite(value) && window.__bullFrames.at(-1) !== value) window.__bullFrames.push(value);
    });
    window.__bullObserver.observe(card, { attributes: true, attributeFilter: ['data-frame-index'] });
  });
  await qaClick(motionPage, targetSelector);
  await waitForSettled(motionPage);
  const frames = await motionPage.evaluate(() => {
    window.__bullObserver?.disconnect?.();
    return window.__bullFrames;
  });
  assert.equal(frames[0], 100, 'transition must start at neutral frame 100');
  assert.equal(frames.at(-1), expectedEnd, `transition must end at frame ${expectedEnd}`);
  assert.equal(frames.length, 21, '10 percentage points must render 20 adjacent half-percent steps');
  for (let index = 1; index < frames.length; index += 1) {
    assert.equal(frames[index] - frames[index - 1], direction, `frame ${index} jumped instead of moving one half-percent step`);
  }
}

await captureTransition('#qa-short60', 80, -1);
await qaClick(motionPage, '#qa-neutral');
await waitForSettled(motionPage);
await captureTransition('#qa-long60', 120, 1);
await motionCard.screenshot({ path: 'artifacts/portfolio-impact/smooth-motion-390.png' });
await motionBrowser.close();

console.log('Portfolio Impact exact 900x363 premium composition QA complete');
