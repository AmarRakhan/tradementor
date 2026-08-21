import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { loadAsterSnapshot, mergeCompleteAsterSnapshot, saveAsterSnapshot } from "../lib/aster-snapshot-cache.mjs";
import { createLatestAsterRequestGate, strategy2ServerStatus } from "../lib/aster-strategy2-server-status.mjs";

class Storage {
  values = new Map();
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) { this.values.set(key, value); }
}

const history = { historyAvailable: true, closedTrades: [], realizedEvents: [] };
const account = (uid, enabled) => ({
  configured: true,
  uid,
  positions: [],
  strategy2: { enabled, liveReady: true, phase: enabled ? "RUNNING" : "LIVE_READY", settings: {} },
  strategy3: { settings: {} },
});

test("AAN -> refresh -> AAN remains server-authoritative", () => {
  const before = strategy2ServerStatus(account("user-a", true).strategy2, null, true);
  const after = strategy2ServerStatus(account("user-a", true).strategy2, null, true);
  assert.equal(before.pending, false);
  assert.equal(before.enabled, true);
  assert.equal(after.enabled, true);
  assert.equal(after.label, "AAN");
});

test("an old cached UIT value never becomes a definitive status while loading", () => {
  const storage = new Storage();
  const cached = mergeCompleteAsterSnapshot(account("user-a", false), history);
  saveAsterSnapshot(storage, "user-a", cached, 1234);
  const restored = loadAsterSnapshot(storage, "user-a");
  const view = strategy2ServerStatus(restored?.data.strategy2, null, false);
  assert.equal(view.pending, true);
  assert.equal(view.enabled, null);
  assert.equal(view.liveReady, null);
  assert.equal(view.label, "Serverstatus controleren…");
});

test("a GET started before start confirmation cannot overwrite the confirmed state", () => {
  const gate = createLatestAsterRequestGate();
  const oldGet = gate.begin();
  gate.confirmMutation();
  assert.equal(gate.accepts(oldGet), false);

  const confirmed = strategy2ServerStatus({ enabled: false, liveReady: false }, { enabled: true, liveReady: true, phase: "RUNNING" }, false);
  assert.equal(confirmed.pending, false);
  assert.equal(confirmed.enabled, true);

  const freshGet = gate.begin();
  assert.equal(gate.accepts(freshGet), true);
});

test("logout/login and a full browser restart wait for GET and then restore AAN", () => {
  const storage = new Storage();
  saveAsterSnapshot(storage, "user-a", mergeCompleteAsterSnapshot(account("user-a", false), history), 1234);

  const afterRestart = loadAsterSnapshot(storage, "user-a");
  assert.equal(strategy2ServerStatus(afterRestart?.data.strategy2, null, false).label, "Serverstatus controleren…");

  const freshServer = strategy2ServerStatus(account("user-a", true).strategy2, null, true);
  assert.equal(freshServer.enabled, true);
  assert.equal(freshServer.label, "AAN");
});

test("start, status GET and refresh share one configured Strategy-2 production API", async () => {
  const [genericProxy, strategy2Proxy, route, hook] = await Promise.all([
    readFile(new URL("../lib/cloud-proxy.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/secure-strategy2-live.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/use-exchange-data.ts", import.meta.url), "utf8"),
  ]);
  assert.doesNotMatch(genericProxy, /process\.env\.CLOUD_API_URL/);
  assert.doesNotMatch(strategy2Proxy, /process\.env\.CLOUD_API_URL/);
  assert.match(genericProxy, /tradementor-api-604335232956\.europe-west4\.run\.app/);
  assert.match(strategy2Proxy, /tradementor-api-604335232956\.europe-west4\.run\.app/);
  assert.match(route, /proxyCloud\(request, "\/v1\/me\/aster\/status", "GET"\)/);
  assert.match(hook, /timedRead\("\/api\/exchanges\/aster"\)/);
  assert.match(hook, /confirmMutation\(\)/);
  assert.match(hook, /gate\?\.accepts\(requestToken\)/);
  assert.match(hook, /fetchAsterSnapshot\(uid, requestToken\?\.generation/);
});
