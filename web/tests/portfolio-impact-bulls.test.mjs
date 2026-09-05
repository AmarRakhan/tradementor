import test from "node:test";
import assert from "node:assert/strict";
import { deriveBattleMetrics, positionExposure } from "../lib/portfolio-impact-battle.mjs";

const derive = (longPnl, shortPnl, extra = {}) => deriveBattleMetrics({ longPnl, shortPnl, equity: 10_000, longExposure: 5_000, shortExposure: 5_000, ...extra });

test("absolute P&L stays descriptive while neutral live deltas keep the battle balanced", () => {
  const result = derive(-20, -150);
  assert.equal(result.netPnl, -170);
  assert.equal(result.state, "BOTH_NEGATIVE");
  assert.equal(result.status, "IN EVENWICHT");
  assert.equal(result.barLabel, "LIVE DRUK");
  assert.equal(result.longShare, 50);
  assert.equal(result.shortShare, 50);
});

test("rising long P&L and falling short P&L mean longs are pressing harder", () => {
  const result = derive(-40, -120, { longDelta: 8, shortDelta: -7 });
  assert.equal(result.status, "LONGS DRUKKEN HARDER");
  assert.ok(result.motionBias > 0);
  assert.ok(result.longShare > result.shortShare);
});

test("rising short P&L and falling long P&L mean shorts are pressing harder", () => {
  const result = derive(-40, -120, { longDelta: -6, shortDelta: 9 });
  assert.equal(result.status, "SHORTS DRUKKEN HARDER");
  assert.ok(result.motionBias < 0);
  assert.ok(result.shortShare > result.longShare);
});

test("tiny quote noise does not create a fake dominant side", () => {
  const result = derive(-40, -120, { longDelta: 0.01, shortDelta: -0.01 });
  assert.equal(result.status, "IN EVENWICHT");
  assert.ok(Math.abs(result.longShare - 50) <= 1);
});

test("current loss size does not decide who is pressing now", () => {
  const result = derive(-10, -900, { longDelta: 12, shortDelta: -4 });
  assert.equal(result.status, "LONGS DRUKKEN HARDER");
  assert.ok(result.longShare > 50);
});

test("position count and exposure do not decide live pressure", () => {
  const result = deriveBattleMetrics({ longPnl: -10, shortPnl: -90, longDelta: -3, shortDelta: 8, longExposure: 100_000, shortExposure: 1_000, equity: 10_000 });
  assert.equal(result.status, "SHORTS DRUKKEN HARDER");
  assert.ok(result.shortShare > result.longShare);
});

test("rolling delta can make a rapidly recovering long the live momentum leader", () => {
  const result = deriveBattleMetrics({ longPnl: -400, shortPnl: 100, longDelta: 60, shortDelta: -10, longExposure: 5_000, shortExposure: 5_000, equity: 10_000 });
  assert.equal(result.status, "LONGS DRUKKEN HARDER");
  assert.ok(result.motionBias > 0);
});

test("bar always describes live pressure rather than loss share", () => {
  const result = deriveBattleMetrics({ longPnl: -10, shortPnl: -90, longDelta: 5, shortDelta: -5, longExposure: 100_000, shortExposure: 1_000, equity: 10_000 });
  assert.equal(result.barLabel, "LIVE DRUK");
  assert.ok(result.longShare > result.shortShare);
});

test("exposure derives from notional first and size x mark as fallback", () => {
  assert.equal(positionExposure({ notional: -1234 }), 1234);
  assert.equal(positionExposure({ size: -2, markPrice: 100 }), 200);
  assert.equal(positionExposure({ margin: 20, leverage: 50 }), 1000);
});
