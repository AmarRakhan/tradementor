import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
const maker=fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
test("Multi BB replaces recovery controls with independent bounded DCA",()=>{
  assert.match(maker,/Max DCA LONG/);
  assert.match(maker,/Max DCA SHORT/);
  assert.match(maker,/const maxLong = clampInt\(n\(v\.maxDcaLong\), 0, MAX_DCA\)/);
  assert.match(maker,/const maxShort = clampInt\(n\(v\.maxDcaShort\), 0, MAX_DCA\)/);
  assert.doesNotMatch(maker,/Recovery stage|SHORT VOLLEDIG LOSLATEN/);
});
