import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
const snapshotBridge = await readFile(new URL("../components/aster-profit-pot-snapshot-bridge.tsx", import.meta.url), "utf8");
const spotRoute = await readFile(new URL("../app/api/exchanges/aster/spot-balance/route.ts", import.meta.url), "utf8");
const contract = await readFile(new URL("../lib/financial-data-contract.ts", import.meta.url), "utf8");

test("Profit Pot Snapshot no longer equates Spot wallet balance with today's savings transfers", () => {
  assert.match(page, /PROFIT POT \/ SPOT/);
  assert.match(snapshotBridge, /profit-sweep-settings/);
  assert.match(snapshotBridge, /todayTransferred/);
  assert.doesNotMatch(snapshotBridge, /spot-balance/);
});

test("Spot balance read-only proxy remains available independently", () => {
  assert.match(spotRoute, /asset !== "USDC" && asset !== "USDT"/);
  assert.match(spotRoute, /proxyCloud\(request, `\/v1\/me\/aster\/spot-balance\?asset=\$\{asset\}`, "GET"\)/);
  assert.doesNotMatch(spotRoute, /POST|PUT|DELETE/);
});

test("Profit Pot remains registered as non-trading financial data", () => {
  assert.match(contract, /spotStablecoinBalance/);
  assert.match(contract, /Profit Pot \/ Spot/);
  assert.match(contract, /tradingDecision: false/);
});
