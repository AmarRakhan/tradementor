import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
const chart=fs.readFileSync(new URL("../components/trading-chart.tsx",import.meta.url),"utf8");
test("simple Focus chart has no obsolete fixed recovery trigger",()=>{
  assert.equal(chart.includes("HERSTELTRIGGER · SHORT VRIJ"),false);
  assert.equal(chart.includes("cockpit.rehedgeArmed"),false);
  assert.match(chart,/hedgeReleasePrice/);
  assert.match(chart,/hedgeState/);
  assert.match(chart,/DCA \/ SHORT FILL/);
  assert.match(chart,/SHORT RELEASE/);
});
