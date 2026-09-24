import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Ultra Rivalry is persisted by the existing skin selector and is ASTER-only", async () => {
  const [page, layout, css] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/ultra-rivalry.css", import.meta.url), "utf8"),
  ]);

  assert.match(page, /type AppSkin = "original" \| "suriname-heritage" \| "ultra-rivalry"/);
  assert.match(page, /tradementor\.appSkin/);
  assert.match(page, /onChange\("ultra-rivalry"\)/);
  assert.match(page, />Ultra Rivalry</);
  assert.match(page, /ASTER-only · Goku LONG · Vegeta SHORT · Zeno balance/);
  assert.match(layout, /ultra-rivalry\.css/);

  assert.match(css, /file_000000000ce8820bafd7e295812f41f0/);
  assert.match(css, /file_00000000f090824387a969906f318d64/);
  assert.match(css, /html\[data-app-skin="ultra-rivalry"\]\[data-aster-compact-snapshot="true"\]/);
  assert.match(css, /#aster-portfolio-snapshot-host/);
  assert.match(css, /section\[data-bollinger-score\]/);
  assert.match(css, /\.bottom-nav/);

  // The skin is presentation-only: no application/network/order primitives belong in its stylesheet.
  for (const forbidden of ["/api/", "fetch(", "WebSocket", "authenticatedRequest", "close-profitable", "portfolio-close-all", "PUT ", "POST "]) {
    assert.equal(css.includes(forbidden), false, `presentation CSS must not contain ${forbidden}`);
  }

  // Outside ASTER the Ultra Rivalry stylesheet may only define its Wallet preview tile.
  const withoutPreview = css.replace(/\.skin-preview\.rivalry[\s\S]*?(?=html\[data-app-skin="ultra-rivalry"|$)/, "");
  const unscopedOperationalRule = withoutPreview
    .split("}")
    .map((rule) => rule.trim())
    .filter(Boolean)
    .find((rule) => !rule.startsWith("@") && !rule.includes('html[data-app-skin="ultra-rivalry"][data-aster-compact-snapshot="true"]') && !rule.startsWith("/*"));
  assert.equal(unscopedOperationalRule, undefined);
});

test("Ultra Rivalry does not replace existing ASTER action handlers or data components", async () => {
  const [page, snapshot, battle] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/portfolio-impact-battle.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(snapshot, /portfolio-close-all/);
  assert.match(snapshot, /legacy\.click\(\)/);
  assert.match(snapshot, /Close Long/);
  assert.match(snapshot, /Close Short/);
  assert.match(snapshot, /Close All/);
  assert.match(snapshot, /PORTFOLIOWAARDE/);
  assert.match(snapshot, /AVAILABLE TO TRADE/);
  assert.match(snapshot, /ACTIEF TRADE CAPITAL/);
  assert.match(snapshot, /LIQUIDATIERISICO/);
  assert.match(battle, /PortfolioImpactBullBear/);
  assert.match(battle, /BTC Bollinger timeframe/);

  const selectorStart = page.indexOf("function AppSkinSelector");
  const selectorEnd = page.indexOf("function CompactPositionRow", selectorStart);
  const selector = page.slice(selectorStart, selectorEnd);
  assert.doesNotMatch(selector, /authenticatedRequest|fetch\(|WebSocket|api\//);
});
