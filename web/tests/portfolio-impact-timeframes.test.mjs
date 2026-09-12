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

test("all six requested timeframes remain functional and default stays 15m", () => {
  for (const token of ['id: "1m"', 'id: "5m"', 'id: "15m"', 'id: "1h"', 'id: "4h"', 'id: "24h"']) assert.match(component, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.match(component, /useState<Timeframe>\("15m"\)/);
  assert.match(component, /label: "1u"/);
  assert.match(component, /label: "4u"/);
  assert.doesNotMatch(component, />Exposure</);
  assert.match(component, /Open P&amp;L/);
  assert.match(component, /positionCount/);
  assert.equal(timeframeToAsterInterval("1m"), "1m");
  assert.equal(timeframeToAsterInterval("5m"), "5m");
  assert.equal(timeframeToAsterInterval("15m"), "15m");
  assert.equal(timeframeToAsterInterval("1h"), "1h");
  assert.equal(timeframeToAsterInterval("4h"), "4h");
  assert.equal(timeframeToAsterInterval("24h"), "1d");
});

test("live mark price moves inside whichever timeframe Bollinger bands are selected", () => {
  assert.equal(bollingerScore(100, 100, 200), 0);
  assert.equal(bollingerScore(150, 100, 200), 50);
  assert.equal(bollingerScore(200, 100, 200), 100);
  assert.equal(bollingerScore(151, 100, 200), 51);
  assert.equal(bollingerScore(151, 50, 250), 50.5);
  assert.match(component, /ASTER_BTC_MARK_STREAM/);
  assert.match(component, /btcusdt@markPrice@1s/);
  assert.match(component, /const price = livePrice && livePrice > 0 \? livePrice : bollinger\.price/);
  assert.match(component, /bollingerScore\(price, bollinger\.lower, bollinger\.upper\)/);
});

test("movie movement is continuous playback with smoothing and idle battle motion", () => {
  assert.match(component, /SCORE_SMOOTHING_MS = 1_250/);
  assert.match(component, /IDLE_SWAY_SCORE = 1\.8/);
  assert.match(component, /requestAnimationFrame\(tick\)/);
  assert.match(component, /Math\.sin\(\(now \/ IDLE_PERIOD_MS\)/);
  assert.match(component, /playbackRateForGap/);
  assert.match(component, /\.play\(\)\.catch/);
  assert.match(component, /activeDirectionRef/);
  assert.doesNotMatch(component, /currentTime = targetTime/);
});

test("timeframe changes and data failures preserve the last visual state instead of resetting to 50", () => {
  assert.match(component, /lastValidTargetRef = useRef\(50\)/);
  assert.match(component, /calculatedTargetScore \?\? lastValidTargetRef\.current/);
  assert.match(component, /bollingerCache\.current\.get\(timeframe\)/);
  assert.doesNotMatch(component, /setDisplayScore\(50\)/);
});

test("pressure bar uses the smoothed market score, not the idle movie sway", () => {
  assert.match(component, /const displayLongShare = clampBollingerScore\(displayScore\)/);
  assert.match(component, /const displayShortShare = 100 - displayLongShare/);
  assert.match(component, /"--long-share": `\$\{displayLongShare\}%`/);
  assert.match(component, /setDisplayScore\(nextMarketScore\)/);
  assert.match(component, /const desiredFilmScore = clampBollingerScore\(idleCenter \+ idleOffset\)/);
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
