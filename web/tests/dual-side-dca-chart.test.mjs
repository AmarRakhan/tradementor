import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const chart = readFileSync(new URL("../components/trading-chart.tsx", import.meta.url), "utf8");
const recent = readFileSync(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");

test("Aster detail keeps both active LONG and SHORT next-DCA plans visible", () => {
  assert.match(recent, /detailOppositeSide/);
  assert.match(recent, /detailOppositePosition/);
  assert.match(recent, /detailOppositeRuntime/);
  assert.match(recent, /detailOppositeNextDcaPrice/);
  assert.match(recent, /detailOppositeNextDcaNumber/);
  assert.match(recent, /`\$\{detailOppositeSide\} DCA \$\{Math\.round\(detailOppositeNextDcaNumber\)\}`/);
  assert.match(recent, /Volgende \{detailOppositeSide\} DCA prijs/);
});

test("planned DCA chart rendering supports side-specific keys without touching TP", () => {
  assert.match(chart, /"dca-long"/);
  assert.match(chart, /"dca-short"/);
  assert.match(chart, /level\.key==="dca"\|\|level\.key==="dca-long"\|\|level\.key==="dca-short"/);
  assert.match(chart, /level\.key==="tp"/);
});
