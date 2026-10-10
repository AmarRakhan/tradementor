import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const source = readFileSync(new URL("../lib/use-exchange-data.ts", import.meta.url), "utf8");

test("automatic refreshAll fetches only Aster", () => {
  const start = source.indexOf("const refreshAll = useCallback(");
  const end = source.indexOf("  useEffect(", start);
  assert.ok(start !== -1 && end > start, "refreshAll callback exists");
  const block = source.slice(start, end);
  assert.match(block, /\(\["aster"\] as ExchangeId\[\]\)\.map\(refresh\)/);
  assert.doesNotMatch(block, /\["hyperliquid",\s*"aster"\]/);
});

test("Hyperliquid explicit refresh and historical routes are retained", () => {
  assert.match(source, /exchange === "hyperliquid"/);
  for (const route of [
    "/api/exchanges/hyperliquid",
    "/api/execution/status",
    "/api/exchanges/hyperliquid/dca-deals",
    "/api/exchanges/hyperliquid/closed-trades",
  ]) assert.ok(source.includes(route), route + " remains available");
});

test("Aster fast-start, streaming, 60s refresh and visibility refresh remain", () => {
  assert.match(source, /void refresh\("aster"\)/);
  assert.match(source, /authenticatedStream\("\/api\/exchanges\/aster\/realtime"/);
  assert.match(source, /}, 60_000\)/);
  assert.match(source, /document\.addEventListener\("visibilitychange", visible\)/);
});
