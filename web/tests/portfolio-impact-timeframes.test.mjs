import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dominancePresentation, deriveBattleMetrics } from "../lib/portfolio-impact-battle.mjs";
import { bollingerScore, scoreToTimelineTime, timeframeToAsterInterval } from "../lib/bollinger-battle.mjs";

const component = readFileSync(new URL("../components/portfolio-impact-battle.tsx", import.meta.url), "utf8");
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
  assert.equal(timeframeToAsterInterval("24h"), "1d");
});

test("Bollinger 0 to 100 maps continuously onto the full master timeline", () => {
  assert.equal(bollingerScore(100, 100, 200), 0);
  assert.equal(bollingerScore(150, 100, 200), 50);
  assert.equal(bollingerScore(200, 100, 200), 100);
  assert.equal(scoreToTimelineTime(0, 12), 0);
  assert.equal(scoreToTimelineTime(50, 12), 6);
  assert.equal(scoreToTimelineTime(100, 12), 12);
  assert.match(component, /scoreToTimelineTime\(score, video\.duration\)/);
  assert.match(component, /data-bollinger-score=/);
});

test("visual movement interpolates smoothly instead of stepping through image frames", () => {
  assert.match(component, /requestAnimationFrame\(tick\)/);
  assert.match(component, /easeInOutCubic/);
  assert.match(component, /transitionDurationMs\(from, targetScore\)/);
  assert.match(component, /SEEK_EPSILON_SECONDS = 1 \/ 30/);
  assert.doesNotMatch(component, /portfolio-impact-frames\/frame-|FRAME_COUNT|targetFrameIndex/);
});

test("pressure bar and visible percentages use the same interpolated Bollinger score", () => {
  assert.match(component, /const displayLongShare = clampBollingerScore\(displayScore\)/);
  assert.match(component, /const displayShortShare = 100 - displayLongShare/);
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
