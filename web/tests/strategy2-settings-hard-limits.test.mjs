import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const bridge = fs.readFileSync(new URL("../components/aster-profit-lock-ladder-bridge.tsx", import.meta.url), "utf8");
const guard = fs.readFileSync(new URL("../lib/aster-strategy2-settings-guard.ts", import.meta.url), "utf8");
const settingsRoute = fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts", import.meta.url), "utf8");
const startRoute = fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/start/route.ts", import.meta.url), "utf8");
const simulateRoute = fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/simulate/route.ts", import.meta.url), "utf8");

test("server-side guard caps Strategy 2 exposure controls independently of the browser", () => {
  assert.match(guard, /MAX_TOTAL_POSITIONS = 400/);
  assert.match(guard, /MAX_LONG_SLOTS = 400/);
  assert.match(guard, /MAX_SHORT_SLOTS = 400/);
  assert.match(guard, /MAX_DCA = 500/);
  assert.match(guard, /next\.unlimitedDca = false/);
  assert.match(guard, /next\.maximumPositions = Math\.max\(1, Math\.min\(MAX_TOTAL_POSITIONS/);
});

test("Build 456 preserves an explicit price-zone global maximum instead of rewriting it from legacy LONG+SHORT slots", () => {
  assert.match(guard, /const priceZoneSeats = settings\.priceZoneSeats/);
  assert.match(guard, /\(priceZoneSeats as Record<string, unknown>\)\.enabled === true/);
  assert.doesNotMatch(guard, /settings\.zoneSoldiersEnabled/);
  assert.match(guard, /priceZoneSeatsEnabled && hasExplicitMaximum/);
  assert.match(guard, /finiteInteger\(settings\.maximumPositions \?\? settings\.maximumPairs, 1\)/);
  assert.match(guard, /69L \+ 30S may remain persisted/);
});

test("settings, simulation and live start all pass through the same hard-limit guard", () => {
  for (const route of [settingsRoute, startRoute, simulateRoute]) {
    assert.match(route, /guardedAsterStrategy2Request/);
    assert.match(route, /proxyStrategy2Live\(guarded\.request/);
  }
});

test("missing server settings cannot be silently saved by the Bollinger/Profit Lock bridge", () => {
  assert.match(bridge, /if \(!strategy2\.settings \|\| typeof strategy2\.settings !== "object"/);
  assert.match(bridge, /setSettingsVerified\(false\)/);
  assert.match(bridge, /if \(bbWriteInFlight\.current \|\| !settingsVerified\) return/);
  assert.match(bridge, /disabled=\{busy \|\| !dirty \|\| !settingsVerified\}/);
});
