import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const route = fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts", import.meta.url), "utf8");

test("older settings editors cannot silently turn off Profit Lock Ladder", () => {
  assert.match(route, /profitLockLadderEnabled/);
  assert.match(route, /profitLockLevels/);
  assert.match(route, /profitLockPrimarySide/);
  assert.match(route, /preserveExistingPairOverrides/);
});
