import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const snapshot = fs.readFileSync(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8");

test("aster Snapshot classifies partial account responses without new reads or orders", () => {
  assert.match(snapshot, /result\.authorizationPending===true/);
  assert.match(snapshot, /result\.configured===false/);
  assert.match(snapshot, /!result\.accountTruth \|\| !result\.strategy2/);
  assert.match(snapshot, /ASTER_ACCOUNT_RESPONSE_INCOMPLETE/);
  assert.match(snapshot, /De server leverde geen volledige accountgegevens/);
  assert.match(snapshot, /valuesRef\.current=\{\.\.\.valuesRef\.current,closeDisabled:true\}/);
});
