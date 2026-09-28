import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright";

await mkdir("artifacts/botconfigurator-v31", { recursive: true });
const url = "http://127.0.0.1:4174/tests/visual/botconfigurator-v31.html";
const widths = [320, 360, 390, 412, 430];

for (const width of widths) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width, height: 980 }, deviceScaleFactor: 1 });
  await page.goto(url, { waitUntil: "networkidle" });
  const overview = page.locator(".v31-current");
  await overview.waitFor({ state: "visible" });
  assert.match(await overview.innerText(), /Huidige instellingen/);
  assert.match(await overview.innerText(), /Zone Warriors/);
  assert.match(await overview.innerText(), /3L \+ 3S per zone · max 130/);
  assert.match(await overview.innerText(), /LONG \$0,40 · SHORT \$0,30/);
  let overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  assert.ok(overflow <= 0, width + "px overview horizontal overflow: " + overflow);

  if (width === 390) await page.screenshot({ path: "artifacts/botconfigurator-v31/overview-390.png", fullPage: true });

  await page.getByRole("button", { name: /Wijzigen/ }).click();
  const quick = page.locator(".v31-quick");
  await quick.waitFor({ state: "visible" });
  assert.match(await quick.innerText(), /Instapbedrag/);
  assert.match(await quick.innerText(), /DCA-bedrag/);
  assert.match(await quick.innerText(), /Take profit/);
  assert.match(await quick.innerText(), /Kan hier niet worden gewijzigd/);
  overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  assert.ok(overflow <= 0, width + "px quick-edit horizontal overflow: " + overflow);

  if (width === 320) await page.screenshot({ path: "artifacts/botconfigurator-v31/quick-edit-320.png", fullPage: true });
  if (width === 390) {
    await page.screenshot({ path: "artifacts/botconfigurator-v31/quick-edit-390.png", fullPage: true });
    await page.getByRole("button", { name: /Meer instellingen tonen/ }).click();
    const advanced = page.locator(".v31-advanced");
    await advanced.waitFor({ state: "visible" });
    assert.match(await advanced.innerText(), /Leverage/);
    assert.match(await advanced.innerText(), /Smart Rescue/);
    assert.match(await advanced.innerText(), /Cycle start/);
    assert.match(await advanced.innerText(), /Stoelen resetten naar startinstelling/);
    overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    assert.ok(overflow <= 0, "390px expanded quick-edit horizontal overflow: " + overflow);
    await page.screenshot({ path: "artifacts/botconfigurator-v31/quick-edit-expanded-390.png", fullPage: true });
  }

  await page.getByRole("button", { name: /Annuleren/ }).click();
  await page.getByRole("button", { name: /Instap & DCA/ }).click();
  const seatReset = page.locator(".v3-tp-seat-reset");
  await seatReset.waitFor({ state: "visible" });
  const seatText = await seatReset.innerText();
  assert.match(seatText, /Na behalen doel \(Portfolio TP\)/);
  assert.match(seatText, /Stoelen resetten naar startinstelling/);
  assert.match(seatText, /3L \/ 3S/);
  overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  assert.ok(overflow <= 0, width + "px Portfolio TP seat reset horizontal overflow: " + overflow);
  if (width === 390) await page.screenshot({ path: "artifacts/botconfigurator-v31/portfolio-tp-seat-reset-390.png", fullPage: true });

  await browser.close();
}

console.log("Botconfigurator 3.1 visual QA complete for 320/360/390/412/430px");
