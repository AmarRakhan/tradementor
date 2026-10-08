import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
const code = readFileSync(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8");
test("transient account-truth errors preserve last verified snapshot with visible non-live warning", () => {
  assert.match(code, /setSnapshotLoadWarning\("Accountgegevens tijdelijk niet bijgewerkt/);
  assert.match(code, /if\(valuesRef\.current === EMPTY\)/);
  assert.match(code, /snapshotLoadWarning \? "Niet live" : "Live"/);
  assert.match(code, /snapshotLoadWarning \? <p role="status"/);
  assert.match(code, /setSnapshotLoadWarning\(" "\)/);
});
