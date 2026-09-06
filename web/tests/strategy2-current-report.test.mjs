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

test("total position input waits until blur and preserves long-short ratio", () => {
  assert.match(maker, /totalDraft \?\? v\.positions/);
  assert.match(maker, /onBlur=\{commitTotal\}/);
  assert.match(maker, /Math\.round\(total \* oldLong \/ oldTotal\)/);
});
