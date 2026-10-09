import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (file) => readFileSync(new URL(file, import.meta.url), "utf8");
const loader = read("../lib/cloud-client.ts");
const snapshot = read("../components/aster-portfolio-snapshot-enhancer.tsx");

test("canonical Aster request is shared only for same authenticated user", () => {
  assert.match(loader, /path === "\/api\/exchanges\/aster" && method === "GET"/);
  assert.match(loader, /sharedAsterRequest\?\.uid === uid/);
  assert.match(loader, /observedUid !== uid/);
  assert.match(loader, /firebaseAuth\.currentUser\?\.uid !== uid/);
  assert.match(loader, /entry\.validUntil = Date\.now\(\) \+ 2000/);
});

test("auth completes before account load and 401 token refresh remains", () => {
  assert.match(loader, /await firebaseAuth\.authStateReady\(\)/);
  assert.match(loader, /response\.status === 401/);
  assert.match(loader, /request\(true\)/);
});

test("failed snapshot refresh preserves prior verified data but marks not live", () => {
  assert.match(snapshot, /refreshingSnapshotRef\.current/);
  assert.match(snapshot, /lastConfirmedAtRef\.current=Date\.now\(\)/);
  assert.match(snapshot, /setSnapshotLoadWarning\(stamp/);
  assert.match(snapshot, /closeDisabled:true/);
  assert.match(snapshot, /snapshotLoadWarning \? "Niet live" : "Live"/);
  assert.doesNotMatch(snapshot, /const failed=\{\.\.\.EMPTY,\.\.\.readSnapshotUiState\(\)\}/);
});

test("late response or failure from previous authenticated user is ignored", () => {
  assert.match(snapshot, /await firebaseAuth\.authStateReady\(\)/);
  assert.match(snapshot, /requestUid = firebaseAuth\.currentUser\?\.uid \?\? null/);
  assert.match(snapshot, /if \(!requestUid\) throw new Error\("ASTER_AUTH_NOT_READY"\)/);
  assert.match(snapshot, /firebaseAuth\.currentUser\?\.uid !== requestUid \|\| snapshotUserRef\.current !== requestUid/);
});

test("initial incomplete snapshot is never marked live", () => {
  assert.match(snapshot, /useState\("Accountgegevens laden…"\)/);
  assert.match(snapshot, /setSnapshotLoadWarning\("Accountgegevens laden…"\)/);
});
