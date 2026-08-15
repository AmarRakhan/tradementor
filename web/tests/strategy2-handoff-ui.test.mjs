import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const component=readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
const proxy=readFileSync(new URL("../lib/secure-strategy2-live.ts",import.meta.url),"utf8");

test("handoff remains visible whenever server reports missing or unclear ownership",()=>{
  assert.match(component,/handoffState\.handoffRequired===true/);
  assert.match(component,/Exclusieve overdracht voltooien/);
  assert.match(component,/snapshotFingerprint/);
  assert.match(proxy,/strategy2\/diagnostics/);
  assert.match(proxy,/strategy2\/exclusive-handoff/);
});
