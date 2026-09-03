import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

test("strategy maker keeps legacy live counts but hides a stale minimum-order reason", () => {
  assert.match(maker, /rawReport\.configVersion/);
  assert.match(maker, /const report = rawReport/);
  assert.match(maker, /reportedNotional/);
  assert.match(maker, /settings\.entryNotionalUsd/);
  assert.match(maker, /reasonMatchesSettings \? rawEntryReason : ""/);
  assert.match(maker, /scannedCandidateCount/);
  assert.match(maker, /minimumOrderRejectedCount/);
  assert.match(maker, /nextRequiredEntryMarginUsd/);
  assert.match(maker, /untrackedAccountPositionCount/);
  assert.match(maker, /niet gekoppeld aan Strategy 2/);
});

test("strategy and account position scopes are explicit", () => {
  assert.match(maker, /Botposities:/);
  assert.match(maker, /dashboard telt alle Aster-posities/);
});
