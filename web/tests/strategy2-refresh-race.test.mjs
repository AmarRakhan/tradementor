import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createLatestAsterRequestGate, strategy2ServerStatus } from "../lib/aster-strategy2-server-status.mjs";

const account = (uid, enabled) => ({
  configured: true,
  uid,
  positions: [],
  strategy2: { enabled, liveReady: true, phase: enabled ? "RUNNING" : "LIVE_READY", settings: {} },
});

test("AAN -> refresh -> AAN remains server-authoritative", () => {
  const before = strategy2ServerStatus(account("user-a", true).strategy2, null, true);
  const after = strategy2ServerStatus(account("user-a", true).strategy2, null, true);
  assert.equal(before.pending, false);
  assert.equal(before.enabled, true);
  assert.equal(after.enabled, true);
  assert.equal(after.label, "AAN");
});

test("without a server-confirmed response Strategy 2 stays pending instead of using browser cache", () => {
  const view = strategy2ServerStatus(undefined, null, false);
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

test("logout/login and full browser restart wait for fresh GET and never restore cached Strategy 2", async () => {
  const hook = await readFile(new URL("../lib/use-exchange-data.ts", import.meta.url), "utf8");
  assert.doesNotMatch(hook, /loadAsterSnapshot|saveAsterSnapshot|window\.localStorage/);
  assert.match(hook, /aster: emptySnapshot\(\)/);
  const freshServer = strategy2ServerStatus(account("user-a", true).strategy2, null, true);
  assert.equal(freshServer.enabled, true);
  assert.equal(freshServer.label, "AAN");
});

test("an incomplete server refresh is not merged with older financial fields", async () => {
  const hook = await readFile(new URL("../lib/use-exchange-data.ts", import.meta.url), "utf8");
  assert.doesNotMatch(hook, /preserveConfirmedAsterValues|mergeAsterSnapshotWithHistoryFallback/);
  assert.match(hook, /data: payload/);
});

test("a temporary refresh failure after a confirmed response preserves only current mounted server state", async () => {
  const hook = await readFile(new URL("../lib/use-exchange-data.ts", import.meta.url), "utf8");
  assert.match(hook, /serverConfirmed: current\.snapshots\[exchange\]\.serverConfirmed/);
  assert.doesNotMatch(hook, /saveAsterSnapshot|source: "cache"/);
  const view = strategy2ServerStatus(account("user-a", true).strategy2, null, true);
  assert.equal(view.pending, false);
  assert.equal(view.label, "AAN");
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
