import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const route = await readFile(new URL("../app/api/exchanges/aster/route.ts", import.meta.url), "utf8");
const isolatedProxy = await readFile(new URL("../lib/secure-strategy3-live.ts", import.meta.url), "utf8");

test("Positions reads Strategy 2 from production and Strategy 3 from its isolated project", () => {
  assert.match(route, /Promise\.all/);
  assert.match(route, /proxyCloud\(request, "\/v1\/me\/aster\/status", "GET"\)/);
  assert.match(route, /proxyStrategy3Live\(request, "\/v1\/me\/aster\/status", "GET"\)/);
  assert.match(route, /strategy2: production\.strategy2/);
  assert.match(route, /strategy3: isolated\.strategy3/);
  assert.match(route, /strategy2Tp: productionRow\.strategy2Tp/);
  assert.match(route, /strategy3Tp: isolatedRow\.strategy3Tp/);
  assert.doesNotMatch(route, /unrealizedPnl.*takeProfit|pnl.*TP bereikt/is);
});

test("the isolated proxy is authenticated, read-through and uncached", () => {
  assert.match(isolatedProxy, /STRATEGY3_LIVE_API_URL/);
  assert.match(isolatedProxy, /Authorization: authorization/);
  assert.match(isolatedProxy, /"X-TradeMentor-Client-Mode": "strategy3-live"/);
  assert.match(isolatedProxy, /"cache-control": "no-store"/);
  assert.doesNotMatch(isolatedProxy, /private.?key|wallet.?key|secret/i);
});
