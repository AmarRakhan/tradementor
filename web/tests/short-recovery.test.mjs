import test from "node:test";
import assert from "node:assert/strict";
import { recoveryLadder, recoveryRows, validateRecoverySettings } from "../lib/short-recovery.mjs";

test("free settings validate like the backend", () => {
  assert.equal(validateRecoverySettings(4, "2").ok, true);
  assert.equal(validateRecoverySettings(10, "0,2").ok, true);
  assert.equal(validateRecoverySettings(0, "2").ok, false);
  assert.equal(validateRecoverySettings(10, "10").ok, false);
  assert.equal(validateRecoverySettings(2.5, "1").ok, false);
});

test("ladder from one fixed anchor", () => {
  assert.deepEqual(recoveryLadder(4, "2").map((r) => r.price), [98, 96, 94, 92]);
  assert.deepEqual(recoveryLadder(4, "2").map((r) => r.remainingPct), [75, 50, 25, 0]);
  assert.deepEqual(recoveryLadder(4, "5").map((r) => r.price), [95, 90, 85, 80]);
});

test("rows read the live or shadow record", () => {
  const pairs = [
    { symbol: "SOLUSDT", currentProtectedQty: 10, shortRecovery: { phase: "LADDER", steps: 4, stepsReached: 1, lastTarget: "7.5", anchor: "100", cycleId: 1, lastEvent: "STEP_REDUCE" } },
    { symbol: "ETHUSDT", currentProtectedQty: 2, shortRecoveryShadow: { phase: "LADDER", steps: 4, stepsReached: 0, lastTarget: "2", cycleId: 1, lastEvent: "CYCLE_STARTED" } },
  ];
  assert.deepEqual(recoveryRows(pairs, true).map((r) => [r.symbol, r.progress, r.hedgePct, r.event]),
    [["SOLUSDT", "1/4", 75, "Afbouwstap"]]);
  assert.deepEqual(recoveryRows(pairs, false).map((r) => r.symbol), ["ETHUSDT"]);
});
