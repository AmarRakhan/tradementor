import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  asterSnapshotCacheKey,
  clearAsterSnapshot,
  loadAsterSnapshot,
  mergeCompleteAsterSnapshot,
  saveAsterSnapshot,
  withBoundedRetry,
} from "../lib/aster-snapshot-cache.mjs";

class Storage {
  values = new Map();
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) { this.values.set(key, value); }
  removeItem(key) { this.values.delete(key); }
}

const account = (uid) => ({ configured: true, uid, positions: [], strategy2: { settings: { baseNotional: 35 } }, strategy3: { settings: { baseNotional: 35 } } });
const history = { historyAvailable: true, closedTrades: [], realizedEvents: [] };

test("Aster cache is strictly isolated by Firebase UID and exchange", () => {
  const storage = new Storage();
  const data = mergeCompleteAsterSnapshot(account("user-a"), history);
  assert.equal(saveAsterSnapshot(storage, "user-a", data, 1234), true);
  assert.equal(loadAsterSnapshot(storage, "user-b"), null);
  assert.equal(loadAsterSnapshot(storage, "user-a")?.data.uid, "user-a");
  assert.notEqual(asterSnapshotCacheKey("user-a"), asterSnapshotCacheKey("user-b"));
});

test("logout clearing makes the account snapshot unavailable", () => {
  const storage = new Storage();
  saveAsterSnapshot(storage, "user-a", mergeCompleteAsterSnapshot(account("user-a"), history), 1234);
  clearAsterSnapshot(storage, "user-a");
  assert.equal(loadAsterSnapshot(storage, "user-a"), null);
});

test("partial or invalid snapshots never replace the last valid value", () => {
  const storage = new Storage();
  const valid = mergeCompleteAsterSnapshot(account("user-a"), history);
  saveAsterSnapshot(storage, "user-a", valid, 1234);
  assert.throws(() => mergeCompleteAsterSnapshot(account("user-a"), { historyAvailable: true }));
  assert.equal(loadAsterSnapshot(storage, "user-a")?.updatedAt, 1234);
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
  assert.match(hook, /Promise\.all\(\[\s*timedRead\("\/api\/exchanges\/aster"\),\s*timedRead\("\/api\/exchanges\/aster\/closed-trades"\)/s);
  assert.match(hook, /inFlight\.get\(key\)/);
  assert.match(hook, /current\.snapshots\[exchange\].*loading: false, serverConfirmed: false/s);
  assert.match(page, /asterActionsAreFresh[\s\S]*snapshot\.serverConfirmed/);
  assert.match(page, /fieldset className="aster-action-gate" disabled=\{!asterActionsEnabled\}/);
  assert.match(page, /PremiumBotCreator[\s\S]*asterActionsAreFresh\(snapshots\.aster, cloudReady\)[\s\S]*creator-existing-engine/);
  assert.match(provider, /window\.addEventListener\("online", resume\)/);
});
