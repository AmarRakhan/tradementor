import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const route = await readFile(new URL("../app/api/exchanges/aster/route.ts", import.meta.url), "utf8");

test("Aster status is sourced only from production", () => {
  assert.match(route, /proxyCloud\(request, "\/v1\/me\/aster\/status", "GET"\)/);
  assert.doesNotMatch(route, /proxyStrategy3Live|mergeAsterProjectStatus|aster-strategy-3|strategy3/);
  assert.doesNotMatch(route, /unrealizedPnl.*takeProfit|pnl.*TP bereikt/is);
});
