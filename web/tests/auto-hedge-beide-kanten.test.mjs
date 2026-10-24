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

test("build 634: grid fields in the afbouw card", () => {
  const card = readFileSync(new URL("../components/short-recovery-card.tsx", import.meta.url), "utf8");
  assert.match(card, /rebuySteps: rebuyN, safetyNetPct: String\(safetyN\)/);
  assert.match(card, /Terugkopen na stappen/);
  assert.match(card, /Noodrem: na volledige afbouw/);
  assert.doesNotMatch(card, /100% sluiten en 90%/);
});

test("build 646: afbouwkaart heeft Terughedgen % (standaard 100) en terugkopen 0 = uit", () => {
  const card = readFileSync(new URL("../components/short-recovery-card.tsx", import.meta.url), "utf8");
  assert.match(card, /Terughedgen \(terugkopen \+ noodrem\)/);
  assert.match(card, /plan\.rehedgePct \?\? "100"/);
  assert.match(card, /rehedgePct: String\(rehedgeN\)/);
  assert.match(card, /\(0 = uit\)/);
  assert.match(card, /geen bescherming meer/);
  assert.doesNotMatch(card, /rehedgeAfterAfbouw/);
  assert.equal(recoveryEventLabel("GRID_DONE_NO_REHEDGE"), "Afgebouwd · niet opnieuw hedgen");
  assert.equal(recoveryEventLabel("WAIT_FOR_REHEDGE_PCT"), "Vangnet · terughedgen loopt");
});

test("build 646: verliesgrens springt niet terug, schuifbalk $1–$100, scherm onder de bovenbalk", () => {
  const bridge = readFileSync(new URL("../components/aster-position-loss-auto-hedge-bridge.tsx", import.meta.url), "utf8");
  assert.equal((bridge.match(/type="range" min="1" max="100"/g) || []).length, 2);
  assert.equal((bridge.match(/<span>\$1<\/span><span>\$10<\/span>/g) || []).length, 2);
  assert.match(bridge, /first \|\| current === prevLong \? nextLong : current/);
  assert.match(bridge, /"AUTO_HEDGE_THRESHOLD"/);
  const css = readFileSync(new URL("../app/position-loss-auto-hedge.css", import.meta.url), "utf8");
  assert.match(css, /#aster-position-loss-auto-hedge-back-host\{top:calc\(28px \+ env\(safe-area-inset-top\)\)\}/);
});

test("build 649: max hedge per kant, verdeling en Omlaag/Omhoog/Noodrem op de kaart", () => {
  const bridge = readFileSync(new URL("../components/aster-position-loss-auto-hedge-bridge.tsx", import.meta.url), "utf8");
  assert.match(bridge, /maxHedgePct: maxLongN/);
  assert.match(bridge, /maxHedgeShortPct: maxShortN/);
  assert.equal((bridge.match(/plah-max-hedge/g) || []).length, 2);
  const card = readFileSync(new URL("../components/short-recovery-card.tsx", import.meta.url), "utf8");
  assert.match(card, /distribution: dist/);
  assert.match(card, /"Sterk oplopend"/);
  assert.match(card, /OMLAAG/); assert.match(card, /OMHOOG/); assert.match(card, /NOODREM/);
  assert.doesNotMatch(card, /Vangnet na extra/);
});

test("build 652: verliesgrens wordt niet meer teruggezet naar $10 bij openen", () => {
  const bridge = readFileSync(new URL("../components/aster-position-loss-auto-hedge-bridge.tsx", import.meta.url), "utf8");
  assert.match(bridge, /const prevLong = serverLong\.current/);
  assert.match(bridge, /first \|\| current === prevLong \? nextLong : current/);
  assert.match(bridge, /saving \|\| !synced\.current \|\| !touched\.current\) return;/);
  assert.doesNotMatch(bridge, /current === serverLong\.current \? nextLong : current/);
  assert.equal((bridge.match(/touched\.current = true/g) || []).length, 9);
});

test("build 654: schakelaars LONG-/SHORT-posities beschermen", () => {
  const bridge = readFileSync(new URL("../components/aster-position-loss-auto-hedge-bridge.tsx", import.meta.url), "utf8");
  assert.match(bridge, /LONG-posities beschermen/);
  assert.match(bridge, /SHORT-posities beschermen/);
  assert.match(bridge, /protectLongPositions: protectLongOn, protectShortPositions: protectShortOn/);
});
