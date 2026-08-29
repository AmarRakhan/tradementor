import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
const chart=fs.readFileSync(new URL("../components/trading-chart.tsx",import.meta.url),"utf8");
test("simple Focus chart has no obsolete fixed recovery trigger",()=>{
  assert.equal(chart.includes("HERSTELTRIGGER · SHORT VRIJ"),false);
  assert.ok(chart.includes("cockpit.rehedgeArmed"));
});
