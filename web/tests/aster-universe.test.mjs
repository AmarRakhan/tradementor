import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
const maker=fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
test("Multi BB exposes user-configurable Top-N Aster volume universe",()=>{assert.match(maker,/Top-N volume/);assert.match(maker,/universeTopN: Math\.max\(1, Math\.round/);assert.doesNotMatch(maker,/Focus 2\.0/);});
test("Multi BB exposes total LONG and SHORT slot counts",()=>{assert.match(maker,/Totaal posities \(max 50\)/);assert.match(maker,/LONG slots \(max 25\)/);assert.match(maker,/SHORT slots \(max 25\)/);assert.match(maker,/const longSlots = clampInt/);assert.match(maker,/const shortSlots = clampInt/);});
