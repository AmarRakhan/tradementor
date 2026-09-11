import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const panel = fs.readFileSync(new URL("../components/aster-profit-lock-ladder-panel.tsx", import.meta.url), "utf8");
const bridge = fs.readFileSync(new URL("../components/aster-profit-lock-ladder-bridge.tsx", import.meta.url), "utf8");
const layout = fs.readFileSync(new URL("../app/layout.tsx", import.meta.url), "utf8");
const route = fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts", import.meta.url), "utf8");

const reference = "file_00000000e8dc82108202dd2e1397c131";

test("Profit Lock Ladder is an opt-in panel tied to the approved reference", () => {
  assert.match(panel, new RegExp(reference));
  assert.match(panel, /Profit Lock Ladder/);
  assert.match(panel, /aria-checked=\{enabled\}/);
  assert.match(panel, /SHORT-primary is niet beschikbaar/);
  assert.match(panel, /100% = LONG \+ Profit Lock SHORT sluiten/);
});

test("bridge mounts beside current Bot Settings and augments Portfolio Snapshot only when enabled", () => {
  assert.match(bridge, /#strategy-2-maker \.compact-settings-grid/);
  assert.match(bridge, /\.side-settings-block/);
  assert.match(bridge, /\.aster-portfolio-snapshot/);
  assert.match(bridge, /snapshotHost && enabled/);
  assert.match(bridge, /PROFIT LOCK LADDER · ACTIEF/);
  assert.match(bridge, /hedgedPositionCount/);
  assert.match(bridge, /row\.nextLevel/);
});

test("settings save is patch-safe and legacy editors preserve Profit Lock fields", () => {
  assert.match(bridge, /profitLockLadderEnabled: enabled/);
  assert.match(bridge, /profitLockLevels: payloadLevels/);
  for (const key of ["profitLockLadderEnabled", "profitLockLevels", "profitLockPrimarySide"]) {
    assert.match(route, new RegExp(`\\"${key}\\"`));
  }
});

test("root layout mounts Profit Lock bridge without replacing existing enhancers", () => {
  assert.match(layout, /AsterProfitLockLadderBridge/);
  assert.match(layout, /<AsterPortfolioSnapshotEnhancer \/>/);
  assert.match(layout, /<Strategy2ReferenceEnhancer \/>/);
  assert.match(layout, /<AsterProfitLockLadderBridge \/>/);
});
