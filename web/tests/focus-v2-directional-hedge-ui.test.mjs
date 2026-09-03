import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
const maker=fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
test("Multi BB has no legacy hedge or re-hedge controls",()=>{
  assert.doesNotMatch(maker,/SHORT RELEASE|FULL SHORT RE-HEDGE|focusV2|focusAirbag|Start LONG \+ SHORT 1:1/i);
  assert.match(maker,/Alle actieve instellingen staan direct hieronder\. Geen wizard/);
});
