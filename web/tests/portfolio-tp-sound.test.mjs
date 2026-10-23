import test from "node:test";
import assert from "node:assert/strict";
import { readFile, stat } from "node:fs/promises";
import { decidePortfolioTpSound, PORTFOLIO_TP_SOUND_MAX_AGE_MS, PORTFOLIO_TP_SOUND_URL } from "../lib/portfolio-tp-sound.mjs";

const now = 1_800_000_000_000;
const panel = await readFile(new URL("../components/profit-notifications.tsx", import.meta.url), "utf8");

test("new recent Portfolio TP plays the horn once and stores its cycleId", () => {
  const latest = { cycleId: "c2", occurredAtMs: now - 5_000 };
  assert.deepEqual(decidePortfolioTpSound({ latest, lastCycleId: "c1", enabled: true, nowMs: now }), { play: true, store: "c2" });
  assert.deepEqual(decidePortfolioTpSound({ latest, lastCycleId: "c2", enabled: true, nowMs: now }), { play: false, store: null });
});

test("EXECUTING then COMPLETED of the same Portfolio TP never plays twice", () => {
  const first = decidePortfolioTpSound({ latest: { cycleId: "c5", phase: "EXECUTING", occurredAtMs: now }, lastCycleId: "c4", enabled: true, nowMs: now });
  assert.equal(first.play, true);
  const second = decidePortfolioTpSound({ latest: { cycleId: "c5", phase: "COMPLETED", occurredAtMs: now }, lastCycleId: first.store, enabled: true, nowMs: now + 30_000 });
  assert.equal(second.play, false);
});

test("old Portfolio TP (app was closed) is stored silently, no horn on opening", () => {
  const latest = { cycleId: "old", occurredAtMs: now - PORTFOLIO_TP_SOUND_MAX_AGE_MS - 1 };
  assert.deepEqual(decidePortfolioTpSound({ latest, lastCycleId: null, enabled: true, nowMs: now }), { play: false, store: "old" });
});

test("horn switched off: remembered but silent; no Portfolio TP yet: nothing", () => {
  assert.deepEqual(decidePortfolioTpSound({ latest: { cycleId: "c7", occurredAtMs: now }, lastCycleId: "c6", enabled: false, nowMs: now }), { play: false, store: "c7" });
  assert.deepEqual(decidePortfolioTpSound({ latest: null, lastCycleId: "c6", enabled: true, nowMs: now }), { play: false, store: null });
});

test("horn file ships with the app and the panel has a per-device switch and test button", async () => {
  const info = await stat(new URL("../public" + PORTFOLIO_TP_SOUND_URL, import.meta.url));
  assert.ok(info.size > 50_000);
  assert.match(panel, /Hoorn bij Portfolio TP/);
  assert.match(panel, /Geluid testen/);
  assert.match(panel, /handleLatestPortfolioTp\(payload\.latestPortfolioTp/);
  assert.match(panel, /installPortfolioTpSoundUnlock/);
});
