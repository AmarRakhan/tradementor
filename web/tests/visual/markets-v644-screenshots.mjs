import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright";

const out = "artifacts/markets-v644";
await mkdir(out, { recursive: true });
const url = "http://127.0.0.1:4176/tests/visual/markets-v644.html";
const errors = [];

for (const width of [320, 390, 430]) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width, height: 844 }, deviceScaleFactor: 2, hasTouch: true, isMobile: true });
  page.on("pageerror", (error) => errors.push(`${width}: ${error.message}`));
  page.on("console", (message) => { if (message.type() === "error") errors.push(`${width} console: ${message.text()}`); });
  await page.goto(url, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "Markets" }).waitFor();
  await page.waitForFunction(() => document.querySelectorAll('[data-market-symbol]').length > 10);
  await page.waitForTimeout(1800);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  assert.ok(overflow <= 0, `${width}px horizontal overflow ${overflow}`);
  const text = await page.locator("section[aria-labelledby=markets-title]").innerText();
  for (const word of ["Alles", "Vrij", "In positie", "BOT", "MANUAL", "Crypto", "Aandelen", "Grondstoffen", "24H VOL", "BB (15m)"]) assert.ok(text.includes(word), `${width}: ${word} ontbreekt`);
  await page.screenshot({ path: `${out}/list-${width}.png`, fullPage: false });

  if (width === 390) {
    await page.screenshot({ path: `${out}/list-390-full.png`, fullPage: true });
    await page.getByRole("button", { name: "Grondstoffen" }).click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${out}/grondstoffen-390.png` });
    await page.getByRole("button", { name: "Alle", exact: true }).click();
    await page.getByRole("button", { name: "MANUAL", exact: true }).click();
    await page.waitForTimeout(300);
    const manualRows = await page.locator("[data-market-symbol]").count();
    assert.equal(manualRows, 1, "MANUAL-filter toont precies SOL");
    await page.getByRole("button", { name: "Alles", exact: true }).click();

    await page.getByRole("button", { name: /Filters en Bollinger/ }).click();
    await page.getByRole("dialog").waitFor();
    await page.waitForTimeout(350);
    await page.screenshot({ path: `${out}/filters-390.png` });
    await page.getByRole("button", { name: "Klaar" }).click();

    // Double tap BTC -> flip to the full-screen Koers chart.
    const btc = page.locator('[data-market-symbol="BTCUSDT"] button').first();
    await btc.scrollIntoViewIfNeeded();
    const box = await btc.boundingBox();
    await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
    await page.waitForTimeout(90);
    await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
    const frames = [];
    for (let frame = 0; frame < 6; frame += 1) {
      await page.waitForTimeout(70);
      frames.push(await page.evaluate(() => { const card = document.querySelector('[role=dialog] [class*=card]'); return card ? { cls: card.className, transform: getComputedStyle(card).transform, anims: card.getAnimations().length } : null; }));
      await page.screenshot({ path: `${out}/flip-frame-${frame}.png` });
    }
    await writeFile(`${out}/flip-frames.json`, JSON.stringify(frames, null, 1));
    await page.getByRole("dialog", { name: /BTC Koers/ }).waitFor();
    await page.waitForTimeout(1600);
    await page.screenshot({ path: `${out}/flip-open-390.png` });
    const stillOnMarkets = await page.evaluate(() => !window.location.hash.includes("aster"));
    assert.ok(stillOnMarkets, "dubbeltik mag het Tradecentrum niet openen");
    const chartBox = await page.locator(".portfolio-koers-stage").boundingBox();
    assert.ok(chartBox && chartBox.height > 450, `grafiek moet het scherm vullen (hoogte ${chartBox?.height})`);
    // Double tap on the chart flips back.
    await page.touchscreen.tap(200, chartBox.y + chartBox.height / 2);
    await page.waitForTimeout(90);
    await page.touchscreen.tap(200, chartBox.y + chartBox.height / 2);
    await page.waitForTimeout(1000);
    assert.equal(await page.getByRole("dialog", { name: /BTC Koers/ }).count(), 0, "dubbeltik op grafiek draait terug");
    await page.screenshot({ path: `${out}/flip-back-390.png` });
  }
  await browser.close();
}
assert.deepEqual(errors.filter((line) => !/fonts\.g|coincap|Failed to load resource/.test(line)), [], "geen fouten in de pagina");
console.log("Markets 644 visual QA OK");
