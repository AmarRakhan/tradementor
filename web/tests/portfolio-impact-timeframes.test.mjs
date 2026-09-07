import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dominancePresentation, deriveBattleMetrics } from "../lib/portfolio-impact-battle.mjs";

const component = readFileSync(new URL("../components/portfolio-impact-battle.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../components/portfolio-impact-battle.module.css", import.meta.url), "utf8");
const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
const route = readFileSync(new URL("../app/api/markets/aster/pressure/route.ts", import.meta.url), "utf8");

test("dominance score remains deterministic while visual motion is presentation-only", () => {
  assert.deepEqual(dominancePresentation(0), { score: 0, longShare: 50, shortShare: 50, stateIndex: 8, status: "IN EVENWICHT", barLabel: "MARKTDRUK" });
  assert.equal(dominancePresentation(82).status, "LONGS DOMINEREN");
  assert.equal(dominancePresentation(-82).status, "SHORTS DOMINEREN");
  assert.equal(dominancePresentation(100).stateIndex, 16);
  assert.equal(dominancePresentation(-100).stateIndex, 0);
});

test("legacy battle helper remains backward-compatible while market score can drive it explicitly", () => {
  const legacy = deriveBattleMetrics({ longPnl: -40, shortPnl: -120, longDelta: 8, shortDelta: -7, longExposure: 5000, shortExposure: 5000, equity: 10000 });
  assert.equal(legacy.status, "LONGS DRUKKEN HARDER");
  const market = deriveBattleMetrics({ longPnl: -40, shortPnl: -120, equity: 10000, dominanceScore: -78 });
  assert.equal(market.status, "SHORTS DOMINEREN");
  assert.equal(market.barLabel, "MARKTDRUK");
});

test("all six requested timeframes remain functional and Exposure stays absent", () => {
  for (const token of ['id: "1m"', 'id: "5m"', 'id: "15m"', 'id: "1h"', 'id: "4h"', 'id: "24h"']) assert.match(component, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.match(component, /label: "1u"/);
  assert.match(component, /label: "4u"/);
  assert.doesNotMatch(component, />Exposure</);
  assert.match(component, /Open P&amp;L/);
  assert.match(component, /positionCount/);
});

test("premium visual engine ships 201 half-percent frames with no bull filter or morph animation", () => {
  const frames = readdirSync(new URL("../public/portfolio-impact-frames/", import.meta.url)).filter((name) => /^frame-\d{3}\.svg$/.test(name));
  assert.equal(frames.length, 201);
  assert.match(component, /const FRAME_COUNT = 201/);
  assert.match(component, /Math\.round\(numberFrom\(longShare\) \* 2\)/);
  assert.match(component, /portfolio-impact-frames\/frame-/);
  const sceneRule = css.match(/\.scene\{[^}]+\}/)?.[0] || "";
  assert.doesNotMatch(sceneRule, /filter:/);
  assert.doesNotMatch(sceneRule, /animation:/);
});

test("a ten percentage-point push is exactly twenty adjacent visual frames", () => {
  const frame = (share) => Math.round(share * 2);
  assert.equal(frame(50), 100);
  assert.equal(frame(40), 80);
  assert.equal(frame(60), 120);
  assert.equal(frame(50) - frame(40), 20);
  assert.equal(frame(60) - frame(50), 20);
  assert.match(component, /current \+ \(targetFrameIndex > current \? 1 : -1\)/);
  assert.match(component, /FRAME_INTERVAL_MS = 25/);
  assert.match(component, /data-frame-index=/);
  assert.match(component, /data-target-frame-index=/);
});

test("pressure bar and visible percentages are driven by the same display frame", () => {
  assert.match(component, /const displayLongShare = frameToShare\(displayFrameIndex\)/);
  assert.match(component, /"--long-share": `\$\{displayLongShare\}%`/);
  assert.match(component, /formatShare\(displayLongShare\)/);
  assert.match(component, /formatShare\(displayShortShare\)/);
});

test("Aster page places Bulls after account metrics and directly before Tradecentrum component", () => {
  const metrics = page.indexOf('label="PORTFOLIOWAARDE"');
  const bulls = page.indexOf('destination === "aster" && <PortfolioImpactBattle');
  const tradeCenter = page.indexOf('destination === "aster" && <AsterRecentTrades');
  assert.ok(metrics >= 0 && bulls > metrics, "Bulls must be below portfolio/account metrics");
  assert.ok(tradeCenter > bulls, "Bulls must be immediately before Aster Tradecentrum");
  const between = page.slice(bulls, tradeCenter);
  assert.doesNotMatch(between, /<section className=/, "No other main section may sit between Bulls and Tradecentrum");
});

test("market-pressure route remains read-only, deterministic and based on candles rather than account Open P&L", () => {
  assert.match(route, /export async function GET/);
  assert.match(route, /deterministic: true/);
  assert.match(route, /readOnly: true/);
  assert.match(route, /fapi\/v1\/klines/);
  assert.match(route, /price \* 0\.42/);
  assert.match(route, /body \* 0\.18/);
  assert.match(route, /momentum \* 0\.22/);
  assert.match(route, /trend \* 0\.18/);
  assert.doesNotMatch(route, /POST|close-all|strategy2\/start|strategy2\/stop|positions\/.*close/);
});
