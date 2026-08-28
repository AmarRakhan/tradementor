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

test("Aster hero renders separate maintenance and liquidation meters in a mobile two-column grid", async()=>{
  const [page,css]=await Promise.all([
    readFile(new URL("../app/page.tsx",import.meta.url),"utf8"),
    readFile(new URL("../app/globals.css",import.meta.url),"utf8"),
  ]);
  assert.match(page,/LIQUIDATIERISICO/);
  assert.match(page,/destination === "aster" && <LiquidationRiskOrbit/);
  assert.match(page,/snapshot\.serverConfirmed.*snapshot\.updatedAt.*120_000/);
  assert.match(page,/risk-orbit risk-\$\{view\.riskTone\}/);
  assert.match(css,/risk-orbits[^}]*grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
  assert.doesNotMatch(page,/riskNumber\s*=.*liquidation/i);
});
