import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Portfolio Koers is a compact Aster equity chart above the existing snapshot", async () => {
  const [page, component, css, layout, route] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-portfolio-equity-chart.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/portfolio-equity-chart.css", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/portfolio-equity/route.ts", import.meta.url), "utf8"),
  ]);

  assert.match(component, /file_00000000c7ec820ab9697735bb027326/);
  assert.match(component, /Portfolio Koers/);
  assert.match(component, /Totale portfolio waarde \(USDT\)/);
  assert.match(component, /CandlestickSeries/);
  assert.match(component, /Bollinger/);
  const helper = await readFile(new URL("../lib/portfolio-equity-chart.ts", import.meta.url), "utf8");
  assert.match(helper, /Entry \\$\\{event\\.side\\}/);
  assert.doesNotMatch(component, /BTCUSDT|ETHUSDT|HYPEUSDT/);
  assert.doesNotMatch(component, /HistogramSeries|Volume/);

  const chartIndex = page.indexOf("<AsterPortfolioEquityChart");
  const metricsIndex = page.indexOf('<section className="metric-strip"');
  const battleIndex = page.indexOf("<PortfolioImpactBattle");
  assert.ok(chartIndex >= 0 && metricsIndex > chartIndex && battleIndex > metricsIndex, "Portfolio Koers must render above snapshot/battle flow");

  assert.match(layout, /portfolio-equity-chart\.css/);
  assert.match(css, /height:clamp\(215px,52vw,258px\)/);
  assert.match(css, /grid-template-columns:minmax\(0,1fr\) 50px/);
  assert.match(css, /is-fullscreen/);
  assert.match(route, /portfolio-equity\/chart/);
});

test("Portfolio Koers keeps compact event semantics without fake volume", async () => {
  const helper = await readFile(new URL("../lib/portfolio-equity-chart.ts", import.meta.url), "utf8");
  assert.match(helper, /💰 \$\{side\} ×\$\{cluster\.length\}/);
  assert.match(helper, /profit-dot/);
  assert.match(helper, /Entry \$\{event\.side\}/);
  assert.match(helper, /bb_upper/);
  assert.match(helper, /bb_lower/);
  assert.match(helper, /formatPortfolioUsd\(event\.equity\)/);
  assert.doesNotMatch(helper, /volume/i);
});

test("Portfolio chart never mutates Aster trading state", async () => {
  const [component, route] = await Promise.all([
    readFile(new URL("../components/aster-portfolio-equity-chart.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/portfolio-equity/route.ts", import.meta.url), "utf8"),
  ]);
  assert.doesNotMatch(component, /method:\s*["']POST["']|close-profitable|order-intents|automation\/close-all/);
  assert.match(route, /"GET"/);
  assert.doesNotMatch(route, /"POST"|close|order/);
});
