import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Build 479 removes the redundant ASTER strategy banner above Portfolio Koers", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.equal(page.includes("STRATEGIE · PRIJSZONE-STOELEN"), false);
  assert.equal(page.includes("Alleen vrije LONG- en SHORT-stoelen in de actieve prijszone mogen na een geldige instap worden gevuld."), false);
  assert.equal(page.includes("aster-strategy-mode"), false);
  assert.equal(page.includes("BotHealthCard"), false);
});

test("Build 479 keeps Portfolio Koers compact and lets visible market data drive the y-axis", async () => {
  const [component, css, version] = await Promise.all([
    readFile(new URL("../components/portfolio-koers-chart.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/portfolio-koers-chart.css", import.meta.url), "utf8"),
    readFile(new URL("../lib/app-version.ts", import.meta.url), "utf8"),
  ]);

  assert.match(version, /WEBAPP_BUILD_NUMBER = "479"/);
  assert.match(component, /scaleMargins:\{top:\.06,bottom:\.06\}/);
  assert.equal(component.includes("lowGuide"), false);
  assert.equal(component.includes("highGuide"), false);
  assert.equal(component.includes("focusPadding"), false);
  assert.match(component, /Build 479: keep the visible price scale driven by the actual candles\/Bollinger data/);

  assert.match(css, /\.portfolio-koers-ui41 \.portfolio-koers-stage\{\s*height:390px;/);
  assert.match(css, /\.portfolio-zone-map\.portfolio-koers-ui41 \.portfolio-koers-stage\{height:340px\}/);
  assert.match(css, /@media\(max-width:385px\)[\s\S]*\.portfolio-zone-map\.portfolio-koers-ui41 \.portfolio-koers-stage\{height:330px\}/);

  for (const preserved of [
    "PORTFOLIO_KOERS_TIMEFRAMES",
    "portfolio-koers-structure-layer",
    "portfolio-koers-event-chip",
    "portfolio-koers-ui41-footer",
  ]) assert.ok(component.includes(preserved), preserved);
});
