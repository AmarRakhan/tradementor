import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

test("strategy maker reports live bot counts from server state", () => {
  assert.match(maker, /rawReport\.activeLong/);
  assert.match(maker, /rawReport\.activeShort/);
  assert.match(maker, /rawReport\.remainingLong/);
  assert.match(maker, /rawReport\.remainingShort/);
  assert.match(maker, /rawReport\.scannedCandidateCount/);
  assert.match(maker, /<b>Botposities<\/b>/);
  assert.match(maker, /<b>Vrije botslots<\/b>/);
});

test("live toggle remains server/readiness gated", () => {
  assert.match(maker, /status\.pending \|\| busy/);
  assert.match(maker, /if \(liveReady\) return action\("start"\)/);
  assert.match(maker, /return checkReadiness\(true\)/);
});

test("position inputs wait until blur and commit through deterministic slot helpers", () => {
  assert.match(maker, /totalDraft \?\? v\.positions/);
  assert.match(maker, /longDraft \?\? v\.longSlots/);
  assert.match(maker, /shortDraft \?\? v\.shortSlots/);
  assert.match(maker, /onBlur=\{commitTotal\}/);
  assert.match(maker, /onBlur=\{commitLong\}/);
  assert.match(maker, /onBlur=\{commitShort\}/);
  assert.match(maker, /splitTotalPositions\(raw\)/);
  assert.match(maker, /applyLongSlots\(v\.positions, raw\)/);
  assert.match(maker, /applyShortSlots\(v\.positions, raw\)/);
});
