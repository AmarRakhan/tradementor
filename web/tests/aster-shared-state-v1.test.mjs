import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("shared Aster status feed is one visible 5s source and keeps realtime stream separate", async () => {
  const source = await readFile(new URL("../lib/cloud-client.ts", import.meta.url), "utf8");
  assert.match(source, /ASTER_SHARED_SNAPSHOT_MAX_AGE_MS = 5000/);
  assert.match(source, /sharedAsterSnapshotListeners/);
  assert.match(source, /ensureSharedAsterSnapshotFeed/);
  assert.match(source, /document\.visibilityState === "visible"/);
  assert.match(source, /sharedAsterSnapshotInFlight/);
  assert.match(source, /authenticatedStream/);
  assert.match(source, /cache: "no-store"/);
});

test("Aster mutations invalidate shared snapshot immediately", async () => {
  const source = await readFile(new URL("../lib/cloud-client.ts", import.meta.url), "utf8");
  assert.match(source, /path\.startsWith\("\/api\/exchanges\/aster"\)/);
  assert.match(source, /invalidateSharedAsterSnapshot\(\)/);
});

test("Profit Lock no longer owns a 15s Aster status poll", async () => {
  const source = await readFile(new URL("../components/aster-profit-lock-ladder-bridge.tsx", import.meta.url), "utf8");
  assert.match(source, /subscribeSharedAsterSnapshot/);
  assert.doesNotMatch(source, /setInterval\(\(\) => void refresh\(\), 15000\)/);
});

test("Portfolio Cycle no longer owns a 10s Aster status poll", async () => {
  const source = await readFile(new URL("../components/aster-profit-pot-snapshot-bridge.tsx", import.meta.url), "utf8");
  assert.match(source, /subscribeSharedAsterSnapshot/);
  assert.doesNotMatch(source, /setInterval\(refreshCycle, 10000\)/);
  assert.match(source, /profit-sweep-settings/);
});
