import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const guard = fs.readFileSync(new URL("../lib/aster-strategy2-settings-guard.ts", import.meta.url), "utf8");
const settingsRoute = fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts", import.meta.url), "utf8");
const startRoute = fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/start/route.ts", import.meta.url), "utf8");
const simulateRoute = fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/simulate/route.ts", import.meta.url), "utf8");

test("server-side guard caps Strategy 2 exposure controls independently of the browser", () => {
  assert.match(guard, /MAX_TOTAL_POSITIONS = 50/);
  assert.match(guard, /MAX_LONG_SLOTS = 25/);
  assert.match(guard, /MAX_SHORT_SLOTS = 25/);
  assert.match(guard, /MAX_DCA = 500/);
  assert.match(guard, /next\.unlimitedDca = false/);
  assert.match(guard, /next\.maximumPositions = Math\.max\(1, Math\.min\(MAX_TOTAL_POSITIONS/);
});

test("settings, simulation and live start all pass through the same hard-limit guard", () => {
  for (const route of [settingsRoute, startRoute, simulateRoute]) {
    assert.match(route, /guardedAsterStrategy2Request/);
    assert.match(route, /proxyStrategy2Live\(guarded\.request/);
  }
});
