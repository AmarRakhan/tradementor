import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
const maker=fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
test("direct Multi BB settings expose independent per-position TP",()=>{assert.match(maker,/Take Profit LONG/);assert.match(maker,/Take Profit SHORT/);assert.match(maker,/longTakeProfitValue: longTp/);assert.match(maker,/shortTakeProfitValue: shortTp/);assert.doesNotMatch(maker,/Winsttrigger/);});
