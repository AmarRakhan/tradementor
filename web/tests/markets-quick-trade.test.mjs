import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

test("Markets exposes safe Strategy 2 quick trade controls", () => {
  const source=fs.readFileSync(new URL("../components/markets-page.tsx", import.meta.url),"utf8");
  assert.match(source,/Buy Long/); assert.match(source,/Buy Short/);
  assert.match(source,/Open .* LONG|Open \{quickTrade\.row\.symbol\}/);
  assert.match(source,/idempotency_key/); assert.match(source,/strategy2\/quick-trade/);
});

test("Next route proxies quick trade through secure Strategy 2 live proxy", () => {
  const source=fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/quick-trade/route.ts", import.meta.url),"utf8");
  assert.match(source,/proxyStrategy2Live/); assert.match(source,/\/v1\/me\/aster\/strategy2\/quick-trade/);
});
