import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { recoveryLadder, recoveryEventLabel, unwindBadge, validateRecoverySettings } from "../lib/short-recovery.mjs";

// Build 623 (Amar 23-10): Auto Hedge for both sides, separate settings per side.

test("LONG-hedge ladder mirrors the SHORT-hedge ladder (rising price)", () => {
  assert.deepEqual(recoveryLadder(3, "6", 100, "LONG").map((r) => r.price), [102, 104, 106]);
  assert.deepEqual(recoveryLadder(3, "6", 100, "SHORT").map((r) => r.price), [98, 96, 94]);
  assert.deepEqual(recoveryLadder(3, "6").map((r) => r.price), [98, 96, 94]);           // default unchanged
  assert.match(validateRecoverySettings(3, "0", "LONG").message, /Totale stijging/);
  assert.match(validateRecoverySettings(3, "0").message, /Totale daling/);
});

test("new events have a Dutch label", () => {
  assert.equal(recoveryEventLabel("STEP_WAIT_PROFIT_AFTER_FEES"), "Wacht: stap nog geen winst na fees");
  assert.equal(recoveryEventLabel("JOINT_EXIT_NET_POSITIVE_CLOSING_HEDGE"), "TP netto plus · hedge sluiten");
});

test("joint TP exit shows HEDGED · TP via the pairExit field", () => {
  const pair = { status: "HEDGED", currentProtectedQty: 10, pairExit: { phase: "CLOSING_OPPOSITE" },
    shortRecovery: { phase: "LADDER", stepsReached: 0, steps: 3, lastTarget: "10" } };
  assert.equal(unwindBadge(pair).label, "HEDGED · TP");
});

test("Auto Hedge screen has a loss threshold and an afbouw card per side", () => {
  const bridge = readFileSync(new URL("../components/aster-position-loss-auto-hedge-bridge.tsx", import.meta.url), "utf8");
  assert.match(bridge, /LONG-positie · hedge vanaf verlies/);
  assert.match(bridge, /SHORT-positie · hedge vanaf verlies/);
  assert.match(bridge, /thresholdShortUsd: thresholdShort/);
  assert.match(bridge, /hedgeSide="SHORT"/);
  assert.match(bridge, /hedgeSide="LONG"/);
  const card = readFileSync(new URL("../components/short-recovery-card.tsx", import.meta.url), "utf8");
  assert.match(card, /\{ \.\.\.payload, hedgeSide, clientBuild/);
  assert.match(card, /state\.longRecoveryPlan : state\.shortRecoveryPlan/);
  assert.match(card, /Alleen met winst na fees/);
});
