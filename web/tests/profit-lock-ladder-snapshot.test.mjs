import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const bridge = fs.readFileSync(new URL("../components/aster-profit-lock-ladder-bridge.tsx", import.meta.url), "utf8");

test("Portfolio Snapshot exposes weighted Profit Lock coverage and coin drilldown", () => {
  assert.match(bridge, /hedgeCoveragePercent/);
  assert.match(bridge, /profitLockShortExposureUsd/);
  assert.match(bridge, /hedgedPositionCount/);
  assert.match(bridge, /Gewogen Profit Lock SHORT tegenover de actuele LONG exposure/);
  assert.match(bridge, /row\.hedgePercent/);
  assert.match(bridge, /row\.dcaCount/);
});
