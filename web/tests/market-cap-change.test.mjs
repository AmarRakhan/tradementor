import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { formatMarketCapChange, formatMarketCapUsd, marketCapChangeTone, parseMarketCapChange } from "../lib/market-cap-change.mjs";

test("leest de 24u-verandering uit de keyless public API van CoinMarketCap", () => {
  const parsed = parseMarketCapChange({ status: { error_code: 0 }, data: { quote: { USD: { total_market_cap: 2.74e12, total_market_cap_yesterday_percentage_change: -2.98, last_updated: "2026-10-22T15:11:00.000Z" } } } });
  assert.deepEqual(parsed, { changePercent: -2.98, marketCapUsd: 2.74e12, updatedAt: "2026-10-22T15:11:00.000Z" });
});

test("rekent de verandering zelf uit als alleen gisteren bekend is", () => {
  const parsed = parseMarketCapChange({ data: { quote: { USD: { total_market_cap: 103, total_market_cap_yesterday: 100 } } } });
  assert.ok(Math.abs(parsed.changePercent - 3) < 1e-9);
});

test("leest ook de website-API (camelCase) als terugvaloptie", () => {
  const parsed = parseMarketCapChange({ data: { quotes: [{ totalMarketCap: "2740000000000", totalMarketCapYesterdayPercentageChange: "1.25" }] } });
  assert.equal(parsed.changePercent, 1.25);
  assert.equal(parsed.marketCapUsd, 2.74e12);
});

test("geeft null bij een onbruikbaar antwoord en verzint nooit een getal", () => {
  for (const payload of [null, {}, { data: {} }, { data: { quote: { USD: { total_market_cap: 1 } } } }, { data: { quote: { USD: { total_market_cap_yesterday_percentage_change: "abc" } } } }, { data: { quotes: [] } }]) {
    assert.equal(parseMarketCapChange(payload), null);
  }
});

test("toont min of plus, Nederlandse komma, groen bij plus en rood bij min", () => {
  assert.equal(formatMarketCapChange(-2.98), "−2,98%");
  assert.equal(formatMarketCapChange(2.981), "+2,98%");
  assert.equal(formatMarketCapChange(0.001), "0,00%");
  assert.equal(formatMarketCapChange(null), "—");
  assert.equal(marketCapChangeTone(-2.98), "negative");
  assert.equal(marketCapChangeTone(0.5), "positive");
  assert.equal(marketCapChangeTone(-0.001), "neutral");
  assert.equal(marketCapChangeTone(null), "neutral");
  assert.equal(formatMarketCapUsd(2.74e12), "$2.74T");
});

test("de rij Markt staat tussen Rendement vandaag en Close Long, met 3 knoppen in dezelfde stijl", async () => {
  const [component, css, route] = await Promise.all([
    readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/portfolio-snapshot.css", import.meta.url), "utf8"),
    readFile(new URL("../app/api/market-overview/route.ts", import.meta.url), "utf8"),
  ]);
  const growth = component.indexOf('label="RENDEMENT VANDAAG"');
  const market = component.indexOf("<MarketOverviewRow market={market} />");
  const closeLong = component.indexOf('<ProfitAction scope="LONG" label="Close Long"');
  assert.ok(growth > 0 && market > growth && closeLong > market, "volgorde Rendement vandaag → Markt → Close Long");
  assert.match(component, /MARKET CAP 24U/);
  // Build 652: de twee gereserveerde plekken zijn nu LONG en SHORT max drawdown (zelfde kaartstijl).
  assert.equal((component.match(/className="aps-market-card aps-market-placeholder"/g) || []).length, 0);
  assert.ok(component.indexOf('<DrawdownTile side="LONG"') > component.indexOf("MARKET CAP 24U"));
  assert.ok(component.indexOf('<DrawdownTile side="SHORT"') > component.indexOf('<DrawdownTile side="LONG"'));
  assert.match(component, /fetch\("\/api\/market-overview", \{ cache: "no-store" \}\)/);
  assert.match(css, /\.aps-market-row\{display:grid;grid-template-columns:repeat\(3,minmax\(0,1fr\)\)/);
  assert.match(css, /\.aps-market-cap\.aps-positive strong\{color:#42e999\}/);
  assert.match(css, /\.aps-market-cap\.aps-negative strong\{color:#ff6680\}/);
  assert.match(route, /pro-api\.coinmarketcap\.com|CMC_PUBLIC_GLOBAL_METRICS_URL/);
  assert.match(route, /CACHE_MS = 60_000/);
  assert.doesNotMatch(route, /authenticatedRequest|X-CMC_PRO_API_KEY/);
});
