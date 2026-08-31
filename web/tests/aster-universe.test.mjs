import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
const maker=fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
test("Multi BB exposes user-configurable Top-N Aster volume universe",()=>{assert.match(maker,/Top-N Aster-volume/);assert.match(maker,/Top-N volume/);assert.match(maker,/universeTopN:Math\.round/);assert.doesNotMatch(maker,/Focus 2\.0/);});
test("Multi BB exposes total LONG and SHORT slot counts",()=>{assert.match(maker,/Totaal posities/);assert.match(maker,/LONG slots/);assert.match(maker,/SHORT slots/);assert.match(maker,/longSlots:Math\.round/);assert.match(maker,/shortSlots:Math\.round/);});
