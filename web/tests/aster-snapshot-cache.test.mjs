import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  asterSnapshotCacheKey,
  clearAsterSnapshot,
  loadAsterSnapshot,
  mergeCompleteAsterSnapshot,
  mergeAsterSnapshotWithHistoryFallback,
  preserveConfirmedAsterValues,
  saveAsterSnapshot,
  withBoundedRetry,
} from "../lib/aster-snapshot-cache.mjs";

class Storage {
  values = new Map();
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) { this.values.set(key, value); }
  removeItem(key) { this.values.delete(key); }
}

const account = (uid) => ({ configured: true, uid, positions: [], strategy2: { settings: { baseNotional: 35 } } });
const history = { historyAvailable: true, closedTrades: [], realizedEvents: [] };

test("Aster cache is strictly isolated by Firebase UID and exchange", () => {
  const storage = new Storage();
  const data = mergeCompleteAsterSnapshot(account("user-a"), history);
  const now = Date.now();
  assert.equal(saveAsterSnapshot(storage, "user-a", data, now), true);
  assert.equal(loadAsterSnapshot(storage, "user-b"), null);
  assert.equal(loadAsterSnapshot(storage, "user-a")?.data.uid, "user-a");
  assert.notEqual(asterSnapshotCacheKey("user-a"), asterSnapshotCacheKey("user-b"));
});



test("stale Aster cache is rejected after the initial safety window", () => {
  const storage = new Storage();
  const data = mergeCompleteAsterSnapshot(account("user-a"), history);
  saveAsterSnapshot(storage, "user-a", data, Date.now() - 120_001);
  assert.equal(loadAsterSnapshot(storage, "user-a"), null);
});

test("logout clearing makes the account snapshot unavailable", () => {
  const storage = new Storage();
  saveAsterSnapshot(storage, "user-a", mergeCompleteAsterSnapshot(account("user-a"), history), Date.now());
  clearAsterSnapshot(storage, "user-a");
  assert.equal(loadAsterSnapshot(storage, "user-a"), null);
});

test("partial or invalid snapshots never replace the last valid value", () => {
  const storage = new Storage();
  const valid = mergeCompleteAsterSnapshot(account("user-a"), history);
  const now = Date.now();
  saveAsterSnapshot(storage, "user-a", valid, now);
  assert.throws(() => mergeCompleteAsterSnapshot(account("user-a"), { historyAvailable: true }));
  assert.equal(loadAsterSnapshot(storage, "user-a")?.updatedAt, now);
});



test("Strategy-2-only snapshots are valid and incomplete refreshes preserve confirmed values", () => {
  const previous = { ...account("user-a"), ...history, equity: 321.5, availableBalance: 88.25, activeTradeCapital: 77, maintenanceMargin: 12, marginRatio: 0.04, activePositions: 72 };
  const incoming = { ...account("user-a"), ...history, equity: null, availableBalance: undefined, activeTradeCapital: null, maintenanceMargin: null, marginRatio: null, activePositions: 0 };
  const merged = preserveConfirmedAsterValues(previous, incoming);
  assert.equal(merged.equity, 321.5);
  assert.equal(merged.availableBalance, 88.25);
  assert.equal(merged.activeTradeCapital, 77);
  assert.equal(merged.maintenanceMargin, 12);
  assert.equal(merged.marginRatio, 0.04);
  assert.equal(merged.activePositions, 0, "explicit zero is a confirmed value");
  assert.equal("strategy3" in mergeCompleteAsterSnapshot(account("user-a"), history), false);
});

test("temporary read failure is retried once and then succeeds", async () => {
  let calls = 0;
  const result = await withBoundedRetry(async () => {
    calls += 1;
    if (calls === 1) throw new Error("temporary");
    return "ok";
  }, { attempts: 2, delays: [0] });
  assert.equal(result, "ok");
  assert.equal(calls, 2);
});

test("Aster refresh is parallel, deduplicated and fail-closed for actions", async () => {
  const [hook, page, provider] = await Promise.all([
    readFile(new URL("../lib/use-exchange-data.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/auth-provider.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(hook, /Promise\.allSettled\(\[\s*timedRead\("\/api\/exchanges\/aster"\),\s*timedRead\("\/api\/exchanges\/aster\/closed-trades"\)/s);
  assert.match(hook, /mergeAsterSnapshotWithHistoryFallback/);
  assert.match(hook, /inFlight\.get\(key\)/);
  assert.match(hook, /serverConfirmed: current\.snapshots\[exchange\]\.serverConfirmed/);
  assert.match(hook, /function cachedAsterSnapshot\(uid: string\)/);
  assert.match(hook, /loadAsterSnapshot\(window\.localStorage, uid\)/);
  assert.match(hook, /source: "cache", serverConfirmed: false/);
  assert.match(hook, /snapshots: \{ hyperliquid: emptySnapshot\(\), aster: cachedAsterSnapshot\(uid\) \}/);
  assert.match(page, /asterActionsAreFresh[\s\S]*snapshot\.serverConfirmed/);
  assert.match(page, /fieldset className="aster-action-gate" disabled=\{!asterActionsEnabled\}/);
  assert.match(page, /PremiumBotCreator[\s\S]*asterActionsAreFresh\(snapshots\.aster, cloudReady\)[\s\S]*creator-existing-engine/);
  assert.match(provider, /window\.addEventListener\("online", resume\)/);
});


test("history failure never freezes a newer Strategy-2 status", () => {
  const previous = mergeCompleteAsterSnapshot(
    { ...account("user-a"), strategy2: { settings: {}, lastTickAt: "08:30" } },
    { historyAvailable: true, closedTrades: [{ id: "old" }], realizedEvents: [{ id: "old-event" }] },
  );
  const freshAccount = { ...account("user-a"), strategy2: { settings: {}, lastTickAt: "10:48" } };
  const merged = mergeAsterSnapshotWithHistoryFallback(freshAccount, null, previous);
  assert.equal(merged.strategy2.lastTickAt, "10:48");
  assert.equal(merged.historyAvailable, false);
  assert.deepEqual(merged.closedTrades, [{ id: "old" }]);
  assert.deepEqual(merged.realizedEvents, [{ id: "old-event" }]);
});
