import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { formatLiquidationRisk, liquidationNeedleDegrees, liquidationRiskRemaining, liquidationRiskTone, normalizeLiquidationRisk } from "../lib/liquidation-gauge.mjs";

const explicit = [0, 4.7, 25, 50, 75, 95, 99.9, 100];

test("liquidation cockpit maps the requested 0-100 scale without inventing another score", () => {
  for (const value of explicit) assert.equal(normalizeLiquidationRisk(value), value);
  assert.equal(normalizeLiquidationRisk("4,70%"), 4.7);
  assert.equal(normalizeLiquidationRisk(null), null);
  assert.equal(normalizeLiquidationRisk("—"), null);
  assert.equal(normalizeLiquidationRisk(-5), 0);
  assert.equal(normalizeLiquidationRisk(120), 100);
  assert.equal(liquidationNeedleDegrees(0), 0);
  assert.equal(liquidationNeedleDegrees(50), 90);
  assert.equal(liquidationNeedleDegrees(100), 180);
  assert.equal(liquidationRiskRemaining(4.7), 95.3);
});

test("risk zones remain green to red with 100 percent as liquidation boundary", () => {
  assert.equal(liquidationRiskTone(4.7), "safe");
  assert.equal(liquidationRiskTone(25), "caution");
  assert.equal(liquidationRiskTone(50), "high");
  assert.equal(liquidationRiskTone(75), "critical");
  assert.equal(formatLiquidationRisk(4.7), "4,70%");
  assert.equal(formatLiquidationRisk(100), "100%");
});

test("requested live simulation produces deterministic needle movement", () => {
  const sequence = [4.7, 5.1, 6.4, 8.0, 6.2, 4.9];
  const degrees = sequence.map((value) => Number(liquidationNeedleDegrees(value).toFixed(2)));
  assert.deepEqual(degrees, [8.46, 9.18, 11.52, 14.4, 11.16, 8.82]);
  assert.ok(degrees[3] > degrees[0]);
  assert.ok(degrees[5] < degrees[3]);
});

test("portfolio snapshot contains one premium gauge and preserves surrounding controls", () => {
  const component = fs.readFileSync(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8");
  const css = fs.readFileSync(new URL("../app/portfolio-snapshot.css", import.meta.url), "utf8");
  assert.match(component, /file_000000004e80820a80318a3de3ae5abd/);
  assert.match(component, /className="aps-health-grid"/);
  assert.match(component, /<LiquidationGauge/);
  assert.doesNotMatch(component, /aps-status aps-risk/);
  for (const label of ["PORTFOLIOWAARDE", "AVAILABLE TO TRADE", "ACTIEF TRADE CAPITAL", "ACTIEVE POSITIES", "GESLOTEN RESULTAAT", "TRADES GESLOTEN", "Close Long", "Close Short", "Close All"]) assert.ok(component.includes(label), label);
  assert.match(css, /\.aps-gauge-flipper\.is-flipped\{transform:rotateY\(180deg\)\}/);
  assert.match(css, /transition:transform \.72s/);
  assert.match(css, /@media\(max-width:640px\)/);
  assert.match(css, /@media\(max-width:380px\)/);
});
