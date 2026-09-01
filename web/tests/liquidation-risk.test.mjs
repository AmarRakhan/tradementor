import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { liquidationDistancePercent, liquidationRiskTone, mostCriticalLiquidationPosition } from "../lib/liquidation-risk.mjs";

test("LONG liquidation distance uses live mark and exchange liquidationPrice", () => {
  assert.ok(Math.abs(liquidationDistancePercent({ side:"LONG", markPrice:80000, liquidationPrice:69288 }) - 13.39) < 1e-9);
});

test("SHORT liquidation distance uses live mark and exchange liquidationPrice", () => {
  assert.equal(liquidationDistancePercent({ side:"SHORT", markPrice:100, liquidationPrice:112 }), 12);
});

test("directionally impossible liquidation prices are rejected", () => {
  assert.equal(liquidationDistancePercent({ side:"SHORT", markPrice:100, liquidationPrice:32.98 }), null);
  assert.equal(liquidationDistancePercent({ side:"LONG", markPrice:100, liquidationPrice:112 }), null);
});

test("conflicting declared side and signed exchange amount fail closed", () => {
  assert.equal(liquidationDistancePercent({ side:"LONG", positionAmt:-1, markPrice:100, liquidationPrice:70 }), null);
  assert.equal(liquidationDistancePercent({ side:"SHORT", positionAmt:1, markPrice:100, liquidationPrice:112 }), null);
});

test("signed exchange amount can resolve a missing side", () => {
  assert.equal(liquidationDistancePercent({ positionAmt:-2, markPrice:100, liquidationPrice:112 }), 12);
});

test("shared Aster hedge liquidation price only contributes the directionally valid leg", () => {
  const result=mostCriticalLiquidationPosition([
    {symbol:"SOLUSDT",side:"SHORT",mark:103.699,liquidationPrice:50.7354},
    {symbol:"SOLUSDT",side:"LONG",mark:103.699,liquidationPrice:50.7354},
  ]);
  assert.equal(result.position.side,"LONG");
  assert.ok(Math.abs(result.distancePercent - 51.074) < 0.01);
});

test("account liquidation meter selects the smallest valid distance", () => {
  const result=mostCriticalLiquidationPosition([
    {symbol:"ETHUSDT",side:"LONG",mark:100,liquidationPrice:70},
    {symbol:"BTCUSDT",side:"LONG",mark:80000,liquidationPrice:69288},
  ]);
  assert.equal(result.position.symbol,"BTCUSDT");
  assert.ok(result.distancePercent > 13 && result.distancePercent < 14);
});

test("zero, null and invalid liquidation values are ignored", () => {
  assert.equal(liquidationDistancePercent({side:"LONG",mark:100,liquidationPrice:0}),null);
  assert.equal(mostCriticalLiquidationPosition([{side:"LONG",mark:100,liquidationPrice:null}]),null);
});

test("risk thresholds map to green yellow orange red and unknown", () => {
  assert.equal(liquidationRiskTone(25),"safe");
  assert.equal(liquidationRiskTone(15),"caution");
  assert.equal(liquidationRiskTone(8),"high");
  assert.equal(liquidationRiskTone(7.999),"critical");
  assert.equal(liquidationRiskTone(Number.NaN),"unknown");
});

test("Aster hero renders one compact server account-wide liquidation risk gauge", async()=>{
  const [page,css,display,chart]=await Promise.all([
    readFile(new URL("../app/page.tsx",import.meta.url),"utf8"),
    readFile(new URL("../app/globals.css",import.meta.url),"utf8"),
    readFile(new URL("../lib/aster-account-display.ts",import.meta.url),"utf8"),
    readFile(new URL("../components/trading-chart.tsx",import.meta.url),"utf8"),
  ]);
  assert.match(page,/function LiquidationRiskOrbit/);
  assert.match(page,/risk-orbits liquidation-only/);
  assert.match(display,/liquidationRiskPct/);
  assert.match(display,/maintenanceMarginPct/);
  assert.match(display,/liquidationRiskSource/);
  assert.doesNotMatch(display,/maintenanceMargin \/ equityNumber \* 100/);
  assert.doesNotMatch(display,/data\?\.marginRatio/);
  assert.match(display,/minimumFractionDigits: 2, maximumFractionDigits: 2/);
  assert.match(display,/serverConfirmed/);
  assert.match(display,/120_000/);
  assert.match(chart,/aster-detail-account-strip/);
  assert.match(chart,/LIQUIDATIERISICO/);
  assert.match(chart,/accountDisplay\?\.liquidationValue/);
  assert.match(chart,/accountDisplay\?\.equity/);
  assert.match(chart,/accountDisplay\?\.available/);
  assert.match(page,/risk-orbits liquidation-only/);
  assert.match(css,/Aster liquidation-only cockpit/);
  assert.doesNotMatch(page,/riskNumber\s*=.*liquidation/i);
});
