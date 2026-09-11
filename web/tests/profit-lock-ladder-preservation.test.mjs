import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const route = fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts", import.meta.url), "utf8");
const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const bridge = fs.readFileSync(new URL("../components/aster-profit-lock-ladder-bridge.tsx", import.meta.url), "utf8");

test("older settings editors cannot silently turn off Profit Lock Ladder", () => {
  assert.match(route, /profitLockLadderEnabled/);
  assert.match(route, /profitLockLevels/);
  assert.match(route, /profitLockPrimarySide/);
  assert.match(route, /preserveExistingPairOverrides/);
});


test("Profit Lock and Bot Settings saves cannot overwrite each other from stale UI state", () => {
  assert.match(bridge, /const latestSnapshot = await authenticatedRequest\("\/api\/exchanges\/aster", \{ cache: "no-store" \}\)/);
  assert.match(bridge, /const latestSettings = extract\(latestSnapshot\)\.settings/);
  assert.match(maker, /withLatestProfitLockSettings/);
  assert.match(maker, /profitLockLadderEnabled/);
  assert.match(maker, /profitLockLevels/);
  assert.match(maker, /profitLockPrimarySide/);
  assert.match(maker, /settings: outgoingSettings/);
});
