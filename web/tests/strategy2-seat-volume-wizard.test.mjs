import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
const maker=fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
const behavior=fs.readFileSync(new URL("../components/aster-strategy2-behavior.tsx",import.meta.url),"utf8");
test("wizard persists free seat targets and ten-million volume default",()=>{
  assert.match(maker,/maximumLongPositions/); assert.match(maker,/maximumShortPositions/);
  assert.match(maker,/minimumQuoteVolume24hUsdt/); assert.match(maker,/10000000/);
  assert.match(maker,/LONG stoelen/); assert.match(maker,/SHORT stoelen/); assert.match(maker,/Minimum 24h volume \(USDT\)/);
});
test("behavior renders configured seat targets and volume",()=>{
  assert.match(behavior,/settings\.maximumLongPositions/); assert.match(behavior,/settings\.maximumShortPositions/); assert.match(behavior,/minimumQuoteVolume24hUsdt/);
});
