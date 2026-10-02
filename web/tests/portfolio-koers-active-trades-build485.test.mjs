import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Build 485 adds Active Trades without changing the Accountwaarde default", async () => {
  const component = await readFile(new URL("../components/portfolio-koers-chart.tsx", import.meta.url), "utf8");
  assert.ok(component.includes('type PortfolioViewMode="performance"|"account"|"active"'));
  assert.ok(component.includes('useState<PortfolioViewMode>("account")'));
  assert.ok(component.includes('onClick={()=>setViewMode("performance")}'));
  assert.ok(component.includes('onClick={()=>setViewMode("account")}'));
  assert.ok(component.includes('activeTradesAvailable?<button'));
  assert.ok(component.includes('onClick={()=>setViewMode("active")}'));
  assert.ok(component.includes(">PERFORMANCE</button>"));
  assert.ok(component.includes(">ACCOUNTWAARDE</button>"));
  assert.ok(component.includes(">ACTIEVE TRADES</button>"));
});

test("Active Trades is release-gated to BETA and STABLE keeps the existing two-tab view", async () => {
  const [component, backend] = await Promise.all([
    readFile(new URL("../components/portfolio-koers-chart.tsx", import.meta.url), "utf8"),
    readFile(new URL("../../cloud_api/main.py", import.meta.url), "utf8"),
  ]);
  assert.ok(component.includes("features.active_trades_chart"));
  assert.ok(component.includes("setActiveTradesAvailable(activeTradesFeature.enabled===true)"));
  assert.ok(component.includes("activeTradesAvailable?<button"));
  assert.ok(backend.includes('"active_trades_chart": {"status": "TESTEN", "beta": True, "stable": False}'));
  assert.ok(backend.includes('require_release_feature(user, "active_trades_chart")'));
});

test("Active Trades loads only its new read-only endpoint and uses signed candlesticks", async () => {
  const [component, route] = await Promise.all([
    readFile(new URL("../components/portfolio-koers-chart.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/portfolio-chart/active-trades/route.ts", import.meta.url), "utf8"),
  ]);
  assert.ok(component.includes("/api/exchanges/aster/portfolio-chart/active-trades?timeframe="));
  assert.ok(component.includes('viewMode==="active"'));
  assert.ok(component.includes("activeCandles"));
  assert.ok(component.includes("CandlestickSeries"));
  assert.ok(route.includes('"/v1/me/aster/portfolio-chart/active-trades"'));
  assert.ok(route.includes('"GET"'));
  assert.equal(route.includes("POST"), false);
  assert.equal(route.includes("PUT"), false);
  assert.equal(route.includes("DELETE"), false);
});

test("Active Trades summary is mounted only by the active tab", async () => {
  const component = await readFile(new URL("../components/portfolio-koers-chart.tsx", import.meta.url), "utf8");
  const summary = component.indexOf('viewMode==="active"?<section className="portfolio-koers-active-summary"');
  assert.ok(summary > 0);
  for (const label of [
    "Actieve Trades Samenvatting",
    "HUIDIGE OPEN P&amp;L",
    "HOOGSTE VANDAAG",
    "LAAGSTE VANDAAG",
    "HERSTEL VANAF BODEM",
    "LONG BIJDRAGE",
    "SHORT BIJDRAGE",
    "AANTAL ACTIEVE TRADES",
    "NOTIONAL TOTAAL",
  ]) assert.ok(component.includes(label), label);
  assert.equal(component.includes('viewMode==="account"?<section className="portfolio-koers-active-summary"'), false);
  assert.equal(component.includes('viewMode==="performance"?<section className="portfolio-koers-active-summary"'), false);
});

test("Active Trades keeps account-only zone overlays off the PnL axis while preserving the existing footer", async () => {
  const component = await readFile(new URL("../components/portfolio-koers-chart.tsx", import.meta.url), "utf8");
  assert.ok(component.includes('if(viewMode!=="account")'));
  assert.ok(component.includes('viewMode==="account"?<div className="portfolio-koers-structure-layer"'));
  assert.ok(component.includes('className="portfolio-koers-ui41-footer"'));
  assert.ok(component.includes("BB 20,2"));
});

test("Build 486 keeps Active Trades visually aligned with the existing chart", async () => {
  const [css, version] = await Promise.all([
    readFile(new URL("../app/portfolio-koers-chart.css", import.meta.url), "utf8"),
    readFile(new URL("../lib/app-version.ts", import.meta.url), "utf8"),
  ]);
  assert.ok(css.includes("Build 485 · Portfolio Koers · Actieve Trades 1.0"));
  assert.ok(css.includes(".portfolio-koers-active-summary"));
  assert.ok(css.includes(".portfolio-koers-active-summary-grid"));
  assert.match(version, /WEBAPP_BUILD_NUMBER = "486"/);
});

test("Build 486 does not auto-zoom sparse Active Trades candles", async () => {
  const component = await readFile(new URL("../components/portfolio-koers-chart.tsx", import.meta.url), "utf8");
  assert.ok(component.includes("const focusVisibleBars=view.visibleBars;"));
  assert.ok(component.includes("from:candles.length-focusVisibleBars-.5,"));
  assert.equal(component.includes("Math.min(candles.length,view.visibleBars)"), false);
  assert.equal(component.includes("Math.max(-.5,candles.length-focusVisibleBars-.5)"), false);
});
