import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const core = fs.readFileSync(new URL("../../cloud_api/aster_multi_bb_core.py", import.meta.url), "utf8");

test("asymmetric hedge runtime remains available but is removed from normal Botinstellingen UI", () => {
  assert.doesNotMatch(maker, /Asymmetrische short-hedge modus/);
  assert.doesNotMatch(maker, /Gekoppelde paren/);
  assert.doesNotMatch(maker, /Short start-multiplier/);
  assert.doesNotMatch(maker, /SHORT sluiten bij LONG max DCA/);
  assert.match(core, /asymmetric_hedge_enabled/);
  assert.match(core, /_plan_asymmetric_entries/);
  assert.match(core, /ASYM_SHORT_CLOSE/);
});

test("normal settings save does not clear persisted asymmetric state", () => {
  assert.match(maker, /\.\.\.persisted/);
  assert.doesNotMatch(maker, /asymmetricHedgeModeEnabled:/);
  assert.doesNotMatch(maker, /shortStartMultiplier:/);
});

test("readiness UI keeps durable live authorization visible after a transient report", () => {
  assert.match(maker, /Boolean\(state\.liveReady\) \|\| Boolean\(readiness\.liveReady\)/);
});
