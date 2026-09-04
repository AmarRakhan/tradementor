import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const css = fs.readFileSync(new URL("../app/strategy2-reference.css", import.meta.url), "utf8");

test("asymmetric hedge is optional, persisted and visually exposed", () => {
  assert.match(maker, /asymmetricHedgeEnabled: false/);
  assert.match(maker, /asymmetricHedgeModeEnabled: v\.asymmetricHedgeEnabled/);
  assert.match(maker, /shortStartMultiplier/);
  assert.match(maker, /Asymmetrische short-hedge modus/);
  assert.match(maker, /Short DCA actief/);
  assert.match(maker, /Geen cross-rebalancing/);
  assert.match(maker, /LONG take profit blokkeren/);
  assert.match(maker, /SHORT sluiten bij LONG max DCA/);
  assert.match(maker, /Nieuwe cyclus = nieuwe SHORT/);
  assert.match(css, /Asymmetric short hedge settings 2026-09-04/);
});

test("copy states independent DCA behavior and max-DCA release", () => {
  assert.match(maker, /LONG en SHORT volgen daarna zelfstandig hun eigen DCA-regels/);
  assert.match(maker, /DCA’s worden niet tussen beide zijden gerebalanced/);
  assert.match(maker, /Zodra LONG zijn maximale DCA-aantal bereikt, wordt de volledige SHORT gesloten/);
});

test("readiness UI keeps durable live authorization visible after a transient report", () => {
  assert.match(maker, /Boolean\(state\.liveReady\) \|\| Boolean\(readiness\.liveReady\)/);
});
