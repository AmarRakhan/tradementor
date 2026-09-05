import test from "node:test";
import assert from "node:assert/strict";
import { deriveBattleMetrics, positionExposure } from "../lib/portfolio-impact-battle.mjs";

const derive = (longPnl, shortPnl, extra = {}) => deriveBattleMetrics({ longPnl, shortPnl, equity: 10_000, longExposure: 5_000, shortExposure: 5_000, ...extra });

test("scenario A: profitable long dominates losing short", () => {
  const result = derive(100, -50);
  assert.equal(result.netPnl, 50);
  assert.equal(result.state, "LONG_DOMINANT");
  assert.match(result.status, /LONGS/);
  assert.ok(result.motionBias > 0);
});

test("scenario B: profitable short dominates losing long", () => {
  const result = derive(-30, 120);
  assert.equal(result.netPnl, 90);
  assert.equal(result.state, "SHORT_DOMINANT");
  assert.match(result.status, /SHORTS/);
  assert.ok(result.motionBias < 0);
});

test("scenario C: two losing sides report negative pressure, never a fake winner", () => {
  const result = derive(-20, -150);
  assert.equal(result.state, "BOTH_NEGATIVE");
  assert.equal(result.status, "SHORTS DRUKKEN HARDER OMLAAG");
  assert.equal(result.barLabel, "NEGATIEVE DRUK");
  assert.ok(result.shortShare > result.longShare);
});

test("scenario D: both profitable sides are represented as contributors", () => {
  const result = derive(40, 35);
  assert.equal(result.netPnl, 75);
  assert.equal(result.state, "BOTH_POSITIVE");
  assert.match(result.status, /BEIDE KANTEN|LONGS DRUKKEN/);
});

test("scenario E: zero state remains balanced", () => {
  const result = derive(0, 0);
  assert.equal(result.state, "BALANCED");
  assert.equal(result.longShare, 50);
  assert.equal(result.shortShare, 50);
  assert.equal(result.motionBias, 0);
});

test("scenario F: exposure and position count do not decide the battle outcome", () => {
  const result = deriveBattleMetrics({ longPnl: 2, shortPnl: 40, longExposure: 100_000, shortExposure: 1_000, equity: 20_000 });
  assert.equal(result.state, "BOTH_POSITIVE");
  assert.ok(result.shortShare > result.longShare);
});

test("rolling delta can make a rapidly recovering long the live momentum leader", () => {
  const result = deriveBattleMetrics({ longPnl: -40, shortPnl: 10, longDelta: 60, shortDelta: -10, longExposure: 5_000, shortExposure: 5_000, equity: 10_000 });
  assert.ok(result.longScore > result.shortScore);
  assert.ok(result.motionBias > 0);
});

test("exposure derives from notional first and size x mark as fallback", () => {
  assert.equal(positionExposure({ notional: -1234 }), 1234);
  assert.equal(positionExposure({ size: -2, markPrice: 100 }), 200);
  assert.equal(positionExposure({ margin: 20, leverage: 50 }), 1000);
});
