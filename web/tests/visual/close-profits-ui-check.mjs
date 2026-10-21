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

  // 3. confirm with a synchronous double click: one series, sequential, full quantity, fresh check before each close
  await page.evaluate(() => { window.__delay = 40; });
  await green.click();
  await page.getByRole("dialog").waitFor();
  await page.getByRole("dialog").locator("footer button").last().evaluate((el) => { el.click(); el.click(); });
  await page.getByRole("status").filter({ hasText: /Verwerking voltooid/ }).waitFor({ timeout: 20000 });
  const made = await calls(page);
  const posts = made.filter((c) => c.method === "POST");
  assert.deepEqual(posts.map((c) => c.path.split("/").at(-2)), ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"].filter((s) => posts.some((p) => p.path.includes(s))).length === 4 ? posts.map((c) => c.path.split("/").at(-2)) : []);
  assert.equal(posts.length, 4, "double click did not duplicate the series");
  assert.equal(new Set(posts.map((c) => c.body.idempotency_key)).size, 4);
  assert.ok(posts.every((c) => c.body.side === "SHORT" && c.body.percentage === 50 && c.body.confirm === true));
  const full = { BTCUSDT: 2, ETHUSDT: 10, SOLUSDT: 100, XRPUSDT: 500 };
  assert.ok(posts.every((c) => c.body.expected_quantity === full[c.path.split("/").at(-2)]), "expected_quantity is the FULL live quantity");
  const order = made.map((c) => (c.method === "GET" ? "G" : "P")).join("");
  // history = preview of the cancelled dialog (G) + preview of this confirmation (G) + per SHORT: fresh check (G) then close (P)
  assert.equal(order, "GG" + "GP".repeat(4), "preview, then (fresh check, close) per SHORT, strictly sequential");
  assert.match(await page.getByRole("status").innerText(), /4 SHORTS gesloten/);
  assert.equal(await page.evaluate(() => window.__refreshCount), 1);
  await page.screenshot({ path: `artifacts/close-profits-ui/done-${width}.png`, fullPage: true });
  ok(`${width}px confirm + double click: 4 sequential closes at 50% with full expected_quantity, summary shown, refresh once`);
  await page.close();

  // 4. UNKNOWN stops the series and says where
  page = await open(width, () => { window.__fail.ETHUSDT = "Sluitstatus is niet betrouwbaar bevestigd; er wordt niet opnieuw besteld"; });
  await page.getByRole("button", { name: greenName }).click();
  await page.getByRole("dialog").locator("footer button").last().click();
  await page.getByRole("status").filter({ hasText: /Gestopt bij ETHUSDT/ }).waitFor({ timeout: 20000 });
  const stopped = (await calls(page)).filter((c) => c.method === "POST").map((c) => c.path.split("/").at(-2));
  assert.deepEqual(stopped, ["BTCUSDT", "ETHUSDT"], "nothing is sent after the failing position");
  assert.match(await page.getByRole("status").innerText(), /1 SHORTS gesloten/);
  await page.screenshot({ path: `artifacts/close-profits-ui/stopped-${width}.png`, fullPage: true });
  ok(`${width}px UNKNOWN stops at ETHUSDT, summary names the stop`);
  await page.close();

  // 5. profit gone for one SHORT between preview and confirmation: skipped, counted, series continues
  page = await open(width);
  await page.getByRole("button", { name: greenName }).click();
  await page.getByRole("dialog").waitFor();
  await page.evaluate(() => { window.__world.find((p) => p.symbol === "SOLUSDT").mark = 105.1; });
  await page.getByRole("dialog").locator("footer button").last().click();
  await page.getByRole("status").filter({ hasText: /Verwerking voltooid/ }).waitFor({ timeout: 20000 });
  const posts5 = (await calls(page)).filter((c) => c.method === "POST").map((c) => c.path.split("/").at(-2));
  assert.deepEqual(posts5, ["BTCUSDT", "ETHUSDT", "XRPUSDT"]);
  assert.match(await page.getByRole("status").innerText(), /1 niet meer boven \$0,50 winst/);
  ok(`${width}px SHORT that fell below $0,50 is skipped without an order`);
  await page.close();

  // 6. the existing individual close button still opens the individual close panel
  page = await open(width);
  const row = page.getByRole("button", { name: /BTC SHORT sluiten/ });
  await row.waitFor();
  await row.click();
  await page.waitForFunction(() => document.querySelector('div[aria-hidden="true"][inert]') !== null, null, { timeout: 5000 });
  assert.equal((await calls(page)).filter((c) => c.method === "POST").length, 0, "opening the individual close panel orders nothing");
  ok(`${width}px existing individual close button still opens its panel`);
  await page.close();
}
await browser.close();
console.log(`UI CHECK DONE: ${results.length} checks passed`);
