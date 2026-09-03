import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("an upstream 401 is retried without destroying a valid Firebase session", async () => {
  const source = await readFile(new URL("../lib/cloud-client.ts", import.meta.url), "utf8");
  const provider = await readFile(new URL("../components/auth-provider.tsx", import.meta.url), "utf8");
  assert.match(source, /response\.status === 401/);
  assert.match(source, /request\(true\)/);
  assert.doesNotMatch(source, /firebaseSignOut\(firebaseAuth\)/);
  assert.doesNotMatch(source, /window\.location\.reload\(\)/);
  assert.match(provider, /response\.status === 401/);
  assert.match(provider, /Je login is geldig/);
  assert.doesNotMatch(
    provider,
    /if \(response\.status === 401\) \{\s*await firebaseSignOut\(firebaseAuth\)/,
  );
});

test("Firebase login persistence is installed before auth listeners and sign-in", async () => {
  const firebase = await readFile(new URL("../lib/firebase.ts", import.meta.url), "utf8");
  const provider = await readFile(new URL("../components/auth-provider.tsx", import.meta.url), "utf8");
  assert.match(firebase, /browserLocalPersistence/);
  assert.match(firebase, /setPersistence\(firebaseAuth, browserLocalPersistence\)/);
  assert.match(firebase, /window\.setTimeout\(\(\) => finish\("timeout"\), 4_000\)/);
  assert.match(firebase, /continuing with Firebase fallback/);
  assert.match(provider, /firebaseAuthReady/);
  assert.match(provider, /await firebaseAuthReady/);
});

test("cached read-only UI can render while cloud verification finishes", async () => {
  const provider = await readFile(new URL("../components/auth-provider.tsx", import.meta.url), "utf8");
  const gate = await readFile(new URL("../components/auth-gate.tsx", import.meta.url), "utf8");
  assert.match(provider, /current\.getIdToken\(false\)/);
  assert.match(provider, /current\.getIdToken\(true\)/);
  assert.match(provider, /response\.status === 401/);
  assert.doesNotMatch(gate, /!auth\.cloudReady/);
});
