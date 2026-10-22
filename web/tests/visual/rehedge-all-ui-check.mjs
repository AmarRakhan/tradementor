// Browser check of the REAL AsterRecentTrades row with the Re-Hedge All button (Re-Hedge All 1.0).
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright";

await mkdir("artifacts/rehedge-all-ui", { recursive: true });
const browser = await chromium.launch({ headless: true });
const URL_ = "http://127.0.0.1:4175/tests/visual/close-profits-ui.html";
const ok = (name) => console.log("PASS " + name);
const seed = () => {
  window.__ahPairs = [
    { symbol: "ICPUSDT", status: "RECOVERY", long: 150, short: 0 },
    { symbol: "INJUSDT", status: "REHEDGE_ARMED", long: 150, short: 40 },
    { symbol: "BTCUSDT", status: "HEDGED", long: 300, short: 300 },
  ];
};

for (const width of [390, 360, 1280]) {
  const page = await browser.newPage({ viewport: { width, height: 900 }, deviceScaleFactor: 1 });
  page.on("pageerror", (e) => { throw e; });
  await page.goto(URL_, { waitUntil: "networkidle" });
  await page.evaluate(seed);
  const rehedge = page.getByRole("button", { name: /^Re-Hedge All$/ });
  const p25 = page.getByRole("button", { name: /^25\s?%$/ });
  await rehedge.waitFor();
  const a = await rehedge.boundingBox();
  const b = await p25.boundingBox();
  assert.ok(a && b && a.x + a.width <= b.x + 0.5 && Math.abs(a.y - b.y) < 2, `Re-Hedge All directly left of 25% at ${width}`);
  for (const pct of [25, 50, 75, 100]) {
    const box = await page.getByRole("button", { name: new RegExp(`^${pct}\\s?%$`) }).boundingBox();
    assert.ok(box && box.x + box.width <= width + 0.5 && Math.abs(box.y - a.y) < 2, `${pct}% stays on the same row inside the viewport`);
  }
  assert.ok((await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)) <= 0, `no horizontal overflow at ${width}`);
  await page.screenshot({ path: `artifacts/rehedge-all-ui/row-${width}.png`, fullPage: false, clip: { x: 0, y: Math.max(0, a.y - 160), width, height: 320 } });
  ok(`${width}px Re-Hedge All left of 25%, same row, no overflow`);

  await rehedge.click();
  const dialog = page.getByRole("dialog");
  await dialog.waitFor();
  assert.match(await dialog.innerText(), /2 Recovery-posities opnieuw hedgen\?/);
  assert.match(await dialog.innerText(), /ICP · INJ/);
  assert.match(await dialog.innerText(), /nooit groter dan de LONG/);
  assert.ok((await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)) <= 0, `dialog does not overflow at ${width}`);
  await page.screenshot({ path: `artifacts/rehedge-all-ui/dialog-${width}.png`, fullPage: true });
  await dialog.getByRole("button", { name: /Annuleren/ }).click();
  assert.equal((await page.evaluate(() => window.__calls)).filter((c) => c.method === "POST").length, 0, "cancel sends nothing");
  ok(`${width}px dialog lists the Recovery pairs; cancel sends nothing`);

  await page.evaluate(() => { window.__delay = 60; });
  await rehedge.click();
  await page.getByRole("dialog").waitFor();
  await page.getByRole("dialog").locator("footer button").last().evaluate((el) => { el.click(); el.click(); });
  const result = page.getByRole("dialog", { name: "Re-Hedge All resultaat" });
  await result.waitFor({ timeout: 10000 });
  const posts = (await page.evaluate(() => window.__calls)).filter((c) => c.method === "POST");
  assert.equal(posts.length, 1, "double click sends ONE bulk request");
  assert.equal(posts[0].path, "/api/exchanges/aster/position-loss-auto-hedge/rehedge-all");
  assert.equal(posts[0].body.confirm, true);
  const text = await result.innerText();
  assert.match(text, /Re-Hedge All afgerond/);
  assert.match(text, /Recovery-posities gevonden\s*2/);
  assert.match(text, /ICP · Volledig beschermd/);
  await page.screenshot({ path: `artifacts/rehedge-all-ui/result-${width}.png`, fullPage: true });
  await result.getByRole("button", { name: /Sluiten/ }).click();
  ok(`${width}px confirm + double click: one request, summary shown`);

  await rehedge.click();
  await page.getByRole("status").filter({ hasText: /Geen Recovery-posities/ }).waitFor();
  await page.evaluate(() => { window.__autoHedgeOff = true; });
  await rehedge.click();
  await page.getByRole("status").filter({ hasText: /Zet Auto Hedge eerst AAN/ }).waitFor();
  assert.equal((await page.evaluate(() => window.__calls)).filter((c) => c.method === "POST").length, 1);
  ok(`${width}px nothing-to-do and Auto Hedge OFF send nothing`);
  await page.close();
}
await browser.close();
console.log("UI CHECK rehedge-all: all passed");
