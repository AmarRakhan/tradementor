// Browser check of the REAL AsterRecentTrades component: green Close Profits button, confirmation dialog, percentages,
// result message, double click, failure handling, mobile overflow, existing individual close button.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright";

await mkdir("artifacts/close-profits-ui", { recursive: true });
const browser = await chromium.launch({ headless: true });
const URL_ = "http://127.0.0.1:4175/tests/visual/close-profits-ui.html";
const greenName = /Close 4 SHORT profits/;
const results = [];
const ok = (name) => { results.push(name); console.log("PASS " + name); };

async function open(width, setup) {
  const page = await browser.newPage({ viewport: { width, height: 900 }, deviceScaleFactor: 1 });
  page.on("pageerror", (e) => { throw e; });
  await page.goto(URL_, { waitUntil: "networkidle" });
  if (setup) await page.evaluate(setup);
  return page;
}
const calls = (page) => page.evaluate(() => window.__calls);

for (const width of [390, 1280]) {
  // 1. green button: visible, right place (footer of the Tradecentrum card), correct count, inside the viewport
  let page = await open(width);
  const green = page.getByRole("button", { name: greenName });
  await green.waitFor();
  assert.ok(await green.isVisible());
  const box = await green.boundingBox();
  assert.ok(box && box.x >= 0 && box.x + box.width <= width + 0.5, `green button inside viewport at ${width}`);
  const inFooter = await green.evaluate((el) => Boolean(el.closest("footer")) && Boolean(el.closest("article")));
  assert.ok(inFooter, "green button sits in the footer of the Tradecentrum card");
  const label = (await green.innerText()).replace(/\s+/g, " ");
  assert.match(label, /^Close 4 SHORT profits · \S*\d/, "label: " + label);
  console.log("INFO green button label:", label);
  assert.ok((await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)) <= 0, `no horizontal overflow at ${width}`);
  await page.screenshot({ path: `artifacts/close-profits-ui/button-${width}.png`, fullPage: true });
  ok(`${width}px green button visible, correct place and count, no overflow`);

  // 2. percentage + dialog (with Auto Hedge consequence) + cancel does nothing
  await page.getByRole("button", { name: /^50\s?%$/ }).click();
  assert.equal(await page.getByRole("button", { name: /^50\s?%$/ }).getAttribute("aria-pressed"), "true");
  await green.click();
  const dialog = page.getByRole("dialog");
  await dialog.waitFor();
  assert.match(await dialog.innerText(), /4 winstposities sluiten\?/);
  assert.match(await dialog.innerText(), /50% MARKET-sluiting per geselecteerde SHORT/);
  const warning = page.getByTestId("bulk-auto-hedge-warning");
  assert.match(await warning.innerText(), /2 van deze SHORTS vallen onder Auto Hedge/);
  assert.match(await warning.innerText(), /Recovery.*re-hedge blijft UIT/s);
  assert.ok((await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)) <= 0, `dialog does not overflow at ${width}`);
  await page.screenshot({ path: `artifacts/close-profits-ui/dialog-${width}.png`, fullPage: true });
  await dialog.getByRole("button", { name: /Annuleren/ }).click();
  assert.equal(await page.getByRole("dialog").count(), 0);
  assert.equal((await calls(page)).filter((c) => c.method === "POST").length, 0, "cancel places no order");
  ok(`${width}px dialog shows percentage + Auto Hedge consequence; cancel places nothing`);

  // 3. confirm with a synchronous double click: ONE server round, every SHORT closed exactly once at 50% of the FULL size
  await page.evaluate(() => { window.__delay = 40; });
  await green.click();
  await page.getByRole("dialog").waitFor();
  assert.match(await page.getByRole("dialog").innerText(), /hervat je hem zonder dat een munt twee keer wordt verkleind/);
  await page.getByRole("dialog").locator("footer button").last().evaluate((el) => { el.click(); el.click(); });
  await page.getByRole("status").filter({ hasText: /Ronde voltooid/ }).waitFor({ timeout: 20000 });
  const creates = (await calls(page)).filter((c) => c.method === "POST" && c.path === "/api/exchanges/aster/profit-close-rounds");
  assert.equal(creates.length, 1, "double click created one round");
  assert.ok(creates[0].body.confirm === true && creates[0].body.percentage === 50);
  const full = { BTCUSDT: 2, ETHUSDT: 10, SOLUSDT: 100, XRPUSDT: 500 };
  assert.deepEqual(creates[0].body.targets.map((t) => [t.symbol, t.quantity]).sort(), Object.entries(full).sort(), "targets carry the FULL live quantity");
  const closes3 = await page.evaluate(() => window.__closes);
  assert.deepEqual(closes3.map((c) => c.symbol).sort(), Object.keys(full).sort(), "each SHORT closed exactly once");
  assert.ok(closes3.every((c) => Math.abs(c.closed - full[c.symbol] / 2) < 1e-9));
  assert.equal((await calls(page)).filter((c) => c.method === "POST" && /\/close$/.test(c.path)).length, 0, "the phone never calls the per-symbol close");
  assert.match(await page.getByRole("status").innerText(), /4 SHORTS gesloten · 0 overgeslagen · Ronde voltooid\./);
  assert.equal(await page.evaluate(() => window.__refreshCount), 1);
  await page.screenshot({ path: `artifacts/close-profits-ui/done-${width}.png`, fullPage: true });
  ok(`${width}px confirm + double click: one server round, 4 closes at 50% of the full size, summary, refresh once`);
  await page.close();

  // 4. Amar's case: the connection drops after the first close -> the round stays on the server, the green button
  //    becomes "Hervat ronde · 3 resterend"; resuming finishes the SAME round and never closes the first SHORT again
  page = await open(width, () => { window.__offlineAfterCloses = 1; });
  await page.getByRole("button", { name: greenName }).click();
  await page.getByRole("dialog").locator("footer button").last().click();
  await page.getByRole("status").filter({ hasText: /Verbinding onderbroken/ }).waitFor({ timeout: 30000 });
  const resume = page.getByRole("button", { name: /Hervat ronde · 3 resterend/ });
  await resume.waitFor({ timeout: 10000 });
  await page.evaluate(() => { window.__offline = false; window.__offlineAfterCloses = undefined; });   // connection back
  assert.ok(await page.getByRole("button", { name: /Ronde afsluiten/ }).isVisible());
  await page.screenshot({ path: `artifacts/close-profits-ui/resume-${width}.png`, fullPage: true });
  await resume.click();
  await page.getByRole("status").filter({ hasText: /Ronde voltooid/ }).waitFor({ timeout: 20000 });
  const closes4 = await page.evaluate(() => window.__closes);
  assert.deepEqual(closes4.map((c) => c.symbol).sort(), ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"], "every SHORT exactly once over interruption + resume");
  ok(`${width}px connection lost after 1 close: 'Hervat ronde · 3 resterend' finishes the same round, nothing twice`);
  await page.close();

  // 5. one SHORT needs a check (unknown outcome on the server) and one fell below $0,50: both reported, rest closed
  page = await open(width, () => { window.__fail.ETHUSDT = "unknown"; });
  await page.getByRole("button", { name: greenName }).click();
  await page.getByRole("dialog").waitFor();
  await page.evaluate(() => { window.__world.find((p) => p.symbol === "SOLUSDT").mark = 105.1; });
  await page.getByRole("dialog").locator("footer button").last().click();
  await page.getByRole("status").filter({ hasText: /Ronde voltooid/ }).waitFor({ timeout: 20000 });
  const closes5 = (await page.evaluate(() => window.__closes)).map((c) => c.symbol);
  assert.deepEqual(closes5, ["BTCUSDT", "XRPUSDT"]);
  const status5 = await page.getByRole("status").innerText();
  assert.match(status5, /2 SHORTS gesloten · 1 overgeslagen · 1 te controleren in Aster \(ETHUSDT\)/);
  await page.screenshot({ path: `artifacts/close-profits-ui/needs-check-${width}.png`, fullPage: true });
  ok(`${width}px NEEDS_CHECK and below-$0,50 are reported, the rest of the round continues`);
  await page.close();

  // 6. the existing individual close button still opens the individual close panel
  page = await open(width);
  const row = page.locator(`button[aria-label="BTC SHORT sluiten"]`);   // role="cell" on the button, so not getByRole("button")
  await row.waitFor();
  await row.click();
  await page.waitForFunction(() => document.querySelector('div[aria-hidden="true"][inert]') !== null, null, { timeout: 5000 });
  assert.equal((await calls(page)).filter((c) => c.method === "POST").length, 0, "opening the individual close panel orders nothing");
  ok(`${width}px existing individual close button still opens its panel`);
  await page.close();
}
await browser.close();
console.log(`UI CHECK DONE: ${results.length} checks passed`);
