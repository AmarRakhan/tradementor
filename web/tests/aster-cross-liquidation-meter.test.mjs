import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const account = readFileSync(new URL("../lib/aster-account-display.ts", import.meta.url), "utf8");
const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
const backend = readFileSync(new URL("../../cloud_api/main.py", import.meta.url), "utf8");

test("Aster public status exposes the cross-account liquidation fields consumed by the browser", () => {
  for (const field of ["maintenanceMarginPct","liquidationRiskPct","liquidationRiskSource","marginBalance","totalCrossNotional","longNotional","shortNotional","netExposure","grossExposure","positionCountIncluded"]) assert.ok(backend.includes(`"${field}"`), `${field} missing from public Aster status projection`);
  assert.match(account, /data\?\.liquidationRiskPct/);
  assert.match(account, /liquidationRiskSource/);
  assert.doesNotMatch(account, /data\?\.marginRatio/);
});

test("Aster hero has one liquidation meter and no maintenance meter", () => {
  assert.match(page, /risk-orbits liquidation-only/);
  assert.match(page, /function LiquidationRiskOrbit/);
  assert.match(page, /liquidation-risk/);
  assert.match(page, /VEILIG/);
  assert.doesNotMatch(page, /isHyperliquid \|\| destination === "aster"/);
});

test("the remaining liquidation gauge is about half the previous mobile size", () => {
  assert.match(css, /Aster liquidation-only cockpit/);
  assert.match(css, /width:92px;height:92px/);
  assert.match(css, /width:72px;height:72px/);
});
