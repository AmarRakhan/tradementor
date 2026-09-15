import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
const route = await readFile(new URL("../app/api/exchanges/aster/spot-balance/route.ts", import.meta.url), "utf8");
const contract = await readFile(new URL("../lib/financial-data-contract.ts", import.meta.url), "utf8");

test("Aster dashboard shows one read-only Profit Pot from Spot USDC plus USDT", () => {
  assert.match(page, /PROFIT POT \/ SPOT/);
  assert.match(page, /spot-balance\?asset=USDC/);
  assert.match(page, /spot-balance\?asset=USDT/);
  assert.match(page, /total: usdc \+ usdt/);
  assert.match(page, /Alleen-lezen · USDC/);
});

test("Spot balance web proxy only forwards supported stablecoin GETs", () => {
  assert.match(route, /asset !== "USDC" && asset !== "USDT"/);
  assert.match(route, /proxyCloud\(request, `\/v1\/me\/aster\/spot-balance\?asset=\$\{asset\}`, "GET"\)/);
  assert.doesNotMatch(route, /POST|PUT|DELETE/);
});

test("Profit Pot is registered as non-trading financial data", () => {
  assert.match(contract, /spotStablecoinBalance/);
  assert.match(contract, /Profit Pot \/ Spot/);
  assert.match(contract, /tradingDecision: false/);
});
