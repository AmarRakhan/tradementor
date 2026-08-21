import assert from "node:assert/strict";
import test from "node:test";
import { authoritativePositionReturnPct, topProfitPositions } from "../lib/top-profit-positions.mjs";

test("only open positions are sorted by authoritative dollar P&L and capped at five", () => {
  const rows = [
    { id: "closed", symbol: "OLDUSDT", side: "LONG", quantity: 0, unrealizedPnl: 999 },
    ...[1, 6, 3, 5, 2, 4].map((pnl) => ({ id: String(pnl), symbol: `${pnl}USDT`, side: pnl % 2 ? "LONG" : "SHORT", quantity: 1, unrealizedPnl: pnl })),
  ];
  assert.deepEqual(topProfitPositions(rows).map((row) => row.unrealizedPnl), [6, 5, 4, 3, 2]);
});

test("equal P&L has stable immutable-id ordering independent of input order", () => {
  const rows = [
    { id: "b", symbol: "B", side: "SHORT", quantity: 1, unrealizedPnl: 2 },
    { id: "a", symbol: "A", side: "LONG", quantity: 1, unrealizedPnl: 2 },
  ];
  assert.deepEqual(topProfitPositions(rows).map((row) => row.id), ["a", "b"]);
  assert.deepEqual(topProfitPositions(rows.reverse()).map((row) => row.id), ["a", "b"]);
});

test("return percentage prefers supplied fields and falls back to the financial display contract", () => {
  assert.equal(authoritativePositionReturnPct({ roePct: -2.5, unrealizedPnl: 10, notionalUsd: 100 }), -2.5);
  assert.equal(authoritativePositionReturnPct({ roiPct: 0, unrealizedPnl: 10, notionalUsd: 100 }), 0);
  assert.equal(authoritativePositionReturnPct({ unrealizedPnl: 4, notionalUsd: 200 }), 2);
  assert.equal(authoritativePositionReturnPct({ unrealizedPnl: 4, quantity: 2, markPrice: 100 }), 2);
  assert.equal(authoritativePositionReturnPct({ unrealizedPnl: 4, quantity: 2 }), null);
});
