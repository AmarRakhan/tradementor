import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
const maker=fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
test("manual selection treats entry amount as margin and offers unlimited DCA",()=>{
  assert.match(maker,/Start margin \(USDT\)/);
  assert.match(maker,/entrySizingMode: v\.manualEnabled \? "margin" : "notional"/);
  assert.match(maker,/Onbeperkt DCA/);
  assert.match(maker,/unlimitedDca: v\.unlimitedDca/);
});
