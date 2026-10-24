import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { adviseSettings, adviseStake, fitParts, simulate, stakeForParts } from "../lib/hedge-preview.mjs";

// Build 651 (Amar 24-10): live voorbeeld + advies. Zelfde regels als de server.
const AMAR = { steps: 5, totalPct: 10, distribution: "ASCENDING", rebuySteps: 3, rehedgePct: 75, safetyNetPct: 6 };

test("voorbeeld 'daalt en herstelt' volgt de grid: klein eerst omlaag, klein eerst terug (B)", () => {
  const r = simulate(AMAR, "RECOVER");
  const at = (p) => r.points.find((x) => Math.abs(x.price - p) < 1e-6 && x.shortQty !== undefined);
  assert.equal(r.points[0].shortQty, 10);
  assert.ok(Math.abs(at(98).shortQty - 9.333) < 0.01);
  assert.equal(r.points.find((x) => Math.abs(x.price - 90) < 1e-6).shortQty, 0);
  const upAt = (p) => r.points.filter((x) => Math.abs(x.price - p) < 1e-6).pop().shortQty;
  for (const [p, q] of [[96, 0.5], [98, 1.5], [100, 3], [102, 5], [104, 7.5]]) assert.ok(Math.abs(upAt(p) - q) < 0.01, `${p}`);
  assert.equal(r.maxNet, 10);
  assert.equal(r.maxNetFrom, 90);
  assert.ok(r.result > 0);
});

test("voorbeeld 'blijft dalen' laat de noodrem zien (75% terug)", () => {
  const r = simulate(AMAR, "FALL");
  assert.ok(Math.abs(r.noodremAt - 84.6) < 0.01);
  assert.ok(r.noodrem !== null);
  assert.ok(r.points.some((p) => p.events.some((e) => e.type === "NOODREM")));
  assert.ok(Math.abs(r.points.find((p) => p.events.some((e) => e.type === "NOODREM")).shortQty - 7.5) < 1e-9);
});

test("LONG-hedge (SHORT-positie) is gespiegeld", () => {
  const r = simulate(AMAR, "RECOVER", { side: "LONG" });
  assert.equal(r.points.find((x) => Math.abs(x.price - 110) < 1e-6).shortQty, 0);
});

test("advies inleg: $1 x 20 past 2 stappen oplopend, 5 stappen vanaf $4,20; gelijk vanaf $1,40", () => {
  const a = adviseStake({ ...AMAR, leverage: 20, stake: 1 });
  assert.equal(a.current, 2);
  assert.equal(a.recommended, 4.2);
  assert.equal(a.equalAll, 1.4);
  assert.equal(stakeForParts({ parts: 3, totalPct: 10, distribution: "ASCENDING", leverage: 20 }), 1.7);
  assert.equal(fitParts({ hedgeUsd: 20, steps: 5, totalPct: 10 }), 3);
});

test("advies instellingen bij $1 x 20: balans = gelijk 3 stappen, meer winst = oplopend 2, te klein = geen afbouw", () => {
  const b = adviseSettings({ stake: 1, leverage: 20, goal: "BALANCE" });
  assert.deepEqual([b.settings.steps, b.settings.distribution, b.settings.rehedgePct], [3, "EQUAL", 75]);
  const p = adviseSettings({ stake: 1, leverage: 20, goal: "PROFIT" });
  assert.deepEqual([p.settings.steps, p.settings.distribution], [2, "ASCENDING"]);
  assert.equal(adviseSettings({ stake: 0.2, leverage: 20 }).ok, false);
});

test("schermen: voorbeeld in de afbouwkaart, schakelaar 'Hedge mag groter dan positie'", () => {
  const card = readFileSync(new URL("../components/short-recovery-card.tsx", import.meta.url), "utf8");
  assert.match(card, /<HedgePreview hedgeSide=\{hedgeSide\} maxHedgePct=\{maxHedgePct\}/);
  const preview = readFileSync(new URL("../components/hedge-preview.tsx", import.meta.url), "utf8");
  assert.match(preview, /Inleg voor mijn instellingen/);
  assert.match(preview, /Instellingen voor mijn inleg/);
  assert.match(preview, /Neem deze instellingen over/);
  const bridge = readFileSync(new URL("../components/aster-position-loss-auto-hedge-bridge.tsx", import.meta.url), "utf8");
  assert.match(bridge, /Hedge mag groter dan positie/);
  assert.match(bridge, /allowHedgeAbovePosition: allowAboveOn/);
});
