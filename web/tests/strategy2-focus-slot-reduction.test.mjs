import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

test("slot distribution is direct, stable and bounded at 100 total", () => {
  assert.match(maker, /Math\.min\(MAX_TOTAL_POSITIONS, longSlots \+ shortSlots\)/);
  assert.match(maker, /applyLongSlots/);
  assert.match(maker, /applyShortSlots/);
  assert.match(maker, /maximaal 100 totaal/);
  assert.doesNotMatch(maker, /Multi-Focus/);
});
