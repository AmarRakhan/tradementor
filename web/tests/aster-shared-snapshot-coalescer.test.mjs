import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Aster status reads use one short shared client cache without slowing realtime stream", async () => {
  const source = await readFile(new URL("../lib/cloud-client.ts", import.meta.url), "utf8");
  assert.match(source, /ASTER_SHARED_SNAPSHOT_PATH = "\/api\/exchanges\/aster"/);
  assert.match(source, /ASTER_SHARED_SNAPSHOT_MAX_AGE_MS = 2500/);
  assert.match(source, /sharedAsterSnapshotInFlight/);
  assert.match(source, /method === "GET" && path === ASTER_SHARED_SNAPSHOT_PATH/);
  assert.match(source, /return sharedAsterSnapshotRequest\(init\)/);
  assert.match(source, /authenticatedStream/);
  assert.match(source, /cache: "no-store"/);
});

test("Aster mutations invalidate the shared snapshot immediately", async () => {
  const source = await readFile(new URL("../lib/cloud-client.ts", import.meta.url), "utf8");
  assert.match(source, /method !== "GET" && method !== "HEAD" && path\.startsWith\("\/api\/exchanges\/aster"\)/);
  assert.match(source, /invalidateSharedAsterSnapshot\(\)/);
});

test("Shared Aster snapshot cache is scoped to the authenticated user", async () => {
  const source = await readFile(new URL("../lib/cloud-client.ts", import.meta.url), "utf8");
  assert.match(source, /const uid = user\.uid/);
  assert.match(source, /sharedAsterSnapshotCache\.uid === uid/);
  assert.match(source, /sharedAsterSnapshotInFlight\?\.uid === uid/);
});
