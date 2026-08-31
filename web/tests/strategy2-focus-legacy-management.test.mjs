import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
const maker=fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
test("legacy Focus management controls are absent from active maker",()=>{
  assert.doesNotMatch(maker,/focusLive|focusV2|focusSlots|Focus 2\.0 gebruiken|Start LONG \+ SHORT 1:1/);
  assert.match(maker,/multi_bb_v1/);
});
