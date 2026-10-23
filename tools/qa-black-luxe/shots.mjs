// Visual QA for the Black Luxe skin: real production build, staging preview user, phone viewport.
// Screenshots Aster + Wallet under Suriname Heritage (current look) and Black Luxe (new), plus "no saved skin".
import { chromium } from "playwright";
import { writeFileSync } from "node:fs";

const base = process.env.QA_BASE || "http://terminal.local:4310";
const result = [];
const browser = await chromium.launch({ args: ["--host-resolver-rules=MAP terminal.local 127.0.0.1"] });

for (const skin of ["suriname-heritage", "black-luxe", "(none)"]) {
  for (const tab of ["aster", "wallet"]) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
    await context.addInitScript((s) => {
      try { if (s === "(none)") localStorage.removeItem("tradementor.appSkin"); else localStorage.setItem("tradementor.appSkin", s); } catch {}
    }, skin);
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(`${base}/?staging-demo#/${tab}`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(9000);
    const applied = await page.evaluate(() => document.documentElement.dataset.appSkin || "");
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    const name = `${tab}-${skin.replace(/[()]/g, "")}`;
    await page.screenshot({ path: `${name}.png`, fullPage: true });
    result.push({ name, skin, tab, applied, bodyBackground: bg, errors: errors.slice(0, 5) });
    await context.close();
  }
}
await browser.close();
writeFileSync("result.json", JSON.stringify(result, null, 2));
console.log(JSON.stringify(result, null, 2));
