import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const panel = fs.readFileSync(new URL("../components/aster-profit-lock-ladder-panel.tsx", import.meta.url), "utf8");

test("Profit Lock Ladder clearly communicates LONG-only primary trading", () => {
  assert.match(panel, /LONG \(Only\)/);
  assert.match(panel, /SHORT-primary is niet beschikbaar/);
  assert.match(panel, /SHORT wordt alleen gebruikt als profit lock/);
});
