import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
const maker=fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
test("direct settings expose current Multi BB controls only",()=>{
  for(const x of ["Top-N volume","Minimum leverage","Totaal posities","DCA-bedrag LONG","DCA-bedrag SHORT","Take Profit LONG","Take Profit SHORT","CROSS"]) assert.match(maker,new RegExp(x));
  assert.match(maker,/LONG \/ SHORT · DCA & Take Profit/);
  assert.doesNotMatch(maker,/Focus 2\.0|maker-overlay|Strategy Maker openen/);
});
