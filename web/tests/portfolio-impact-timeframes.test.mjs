import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dominancePresentation, deriveBattleMetrics } from "../lib/portfolio-impact-battle.mjs";

const component = readFileSync(new URL("../components/portfolio-impact-battle.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../components/portfolio-impact-battle.module.css", import.meta.url), "utf8");
const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
const route = readFileSync(new URL("../app/api/markets/aster/pressure/route.ts", import.meta.url), "utf8");

test("dominance score maps deterministically to pressure, status and one of 17 states", () => {
  assert.deepEqual(dominancePresentation(0), { score: 0, longShare: 50, shortShare: 50, stateIndex: 8, status: "IN EVENWICHT", barLabel: "MARKTDRUK" });
  assert.equal(dominancePresentation(82).status, "LONGS DOMINEREN");
  assert.equal(dominancePresentation(-82).status, "SHORTS DOMINEREN");
  assert.ok(dominancePresentation(100).stateIndex === 16);
  assert.ok(dominancePresentation(-100).stateIndex === 0);
  assert.ok(dominancePresentation(38).longShare > 50);
  assert.ok(dominancePresentation(-38).shortShare > 50);
});

test("legacy battle helper remains backward-compatible while market score can drive it explicitly", () => {
  const legacy = deriveBattleMetrics({ longPnl: -40, shortPnl: -120, longDelta: 8, shortDelta: -7, longExposure: 5000, shortExposure: 5000, equity: 10000 });
  assert.equal(legacy.status, "LONGS DRUKKEN HARDER");
  const market = deriveBattleMetrics({ longPnl: -40, shortPnl: -120, equity: 10000, dominanceScore: -78 });
  assert.equal(market.status, "SHORTS DOMINEREN");
  assert.equal(market.barLabel, "MARKTDRUK");
});

test("all six requested timeframes are functional controls and Exposure is absent from visible side panels", () => {
  for (const token of ['id: "1m"', 'id: "5m"', 'id: "15m"', 'id: "1h"', 'id: "4h"', 'id: "24h"']) assert.match(component, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.match(component, /label: "1u"/);
  assert.match(component, /label: "4u"/);
  assert.doesNotMatch(component, />Exposure</);
  assert.match(component, /Open P&amp;L/);
  assert.match(component, /positionCount/);
});

test("state-based visual engine ships 17 precomposed assets and does not filter or animate the bull scene", () => {
  const assets = readdirSync(new URL("../public/portfolio-impact-states/", import.meta.url)).filter((name) => /^state-\d\d\.svg$/.test(name));
  assert.equal(assets.length, 17);
  assert.match(component, /portfolio-impact-states\/state-/);
  const sceneRule = css.match(/\.scene\{[^}]+\}/)?.[0] || "";
  assert.doesNotMatch(sceneRule, /filter:/);
  assert.doesNotMatch(sceneRule, /animation:/);
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

test("market-pressure route is read-only, deterministic and based on candles rather than account Open P&L", () => {
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
