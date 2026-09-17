import test from "node:test";
import assert from "node:assert/strict";
import { countOpenAsterPositions, mergeCompleteAsterSnapshot, preserveConfirmedAsterValues } from "../lib/aster-snapshot-cache.mjs";

const history = { historyAvailable: true, closedTrades: [], realizedEvents: [] };
const row = (symbol, side, amount) => ({ symbol, positionSide: side, positionAmt: String(amount) });

test("concrete Aster positions array is authoritative for active position count", () => {
  const account = { configured: true, strategy2: {}, activePositions: 21, positionCountIncluded: 21,
    positions: [row("ZECUSDT", "SHORT", 1), row("ETHUSDT", "LONG", 2), row("BTCUSDT", "LONG", 0)] };
  const merged = mergeCompleteAsterSnapshot(account, history);
  assert.equal(countOpenAsterPositions(merged), 2);
  assert.equal(merged.activePositions, 2);
  assert.equal(merged.positionCountIncluded, 2);
});

test("newer positions array cannot inherit a stale cached activePositions scalar", () => {
  const previous = { configured: true, strategy2: {}, ...history, activePositions: 21, positions: [row("OLDUSDT", "LONG", 1)] };
  const incoming = { configured: true, strategy2: {}, ...history, activePositions: undefined,
    positions: [row("ZECUSDT", "SHORT", 1), row("ETHUSDT", "LONG", 1)] };
  const merged = preserveConfirmedAsterValues(previous, incoming);
  assert.equal(merged.activePositions, 2);
});
