import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const source=fs.readFileSync(new URL("../components/aster-portfolio-snapshot-enhancer.tsx",import.meta.url),"utf8");

test("Snapshot captures user after Firebase auth persistence is restored",()=>{
  const start=source.indexOf("const refresh=async()=>{",source.indexOf("const refreshingSnapshotRef"));
  const segment=source.slice(start,start+1000);
  assert.match(segment,/await firebaseAuth\.authStateReady\(\)/);
  assert.ok(segment.indexOf("await firebaseAuth.authStateReady()")<segment.indexOf("requestUid = firebaseAuth.currentUser?.uid"));
  assert.ok(segment.indexOf("requestUid = firebaseAuth.currentUser?.uid")<segment.indexOf("await loadCanonicalSnapshotValues()"));
  assert.match(segment,/if \(!requestUid\) throw new Error\("ASTER_AUTH_NOT_READY"\)/);
});
