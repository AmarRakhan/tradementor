import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
const maker=fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
test("old handoff UI is retired while server confirmation remains explicit",()=>{
  assert.doesNotMatch(maker,/Exclusieve overdracht voltooien/);
  assert.match(maker,/Instellingen server-side opgeslagen/);
  assert.match(maker,/server bevestigt actief/);
  assert.match(maker,/onConfirmed\(confirmed\)/);
});
