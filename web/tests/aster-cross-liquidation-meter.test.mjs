import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const account = readFileSync(new URL("../lib/aster-account-display.ts", import.meta.url), "utf8");
const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");

test("Aster frontend consumes separate server-authoritative maintenance and liquidation values", () => {
  assert.match(account, /data\?\.maintenanceMarginPct/);
  assert.match(account, /data\?\.liquidationRiskPct/);
  assert.match(account, /liquidationRiskSource/);
  assert.doesNotMatch(account, /maintenanceMargin\s*\/\s*equity/);
  assert.doesNotMatch(account, /marginRatio\s*\*\s*100/);
});

test("left orbit is maintenance rate and right orbit is liquidation risk", () => {
  assert.match(page, /riskLabel = "MAINTENANCE MARGIN"/);
  assert.match(page, /asterAccountDisplay\?\.maintenanceMarginPercent/);
  assert.match(page, /function LiquidationRiskOrbit/);
  assert.match(page, /LIQUIDATIERISICO/);
  assert.match(page, /positionCountIncluded/);
  assert.doesNotMatch(page, /riskNumber = accountDataAvailable \? asNumber\(data\.marginRatio\) \* 100/);
});

test("Aster risk orbits are compact on mobile and desktop", () => {
  assert.match(css, /Aster cross-risk meters: compact/);
  assert.match(css, /width:152px/);
  assert.match(css, /width:136px/);
});
