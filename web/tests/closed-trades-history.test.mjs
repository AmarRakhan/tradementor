import test from "node:test";
import assert from "node:assert/strict";
import {closedTradeDurationMs,verifiedClosedTradeMargin,uniqueClosedTrades,closedTradeTime} from "../lib/closed-trades-history.mjs";
test("margin must come from a recorded margin field, never inferred from leverage",()=>{
  assert.equal(verifiedClosedTradeMargin({notionalUsd:100,leverage:10}),null);
  assert.equal(verifiedClosedTradeMargin({executedMarginUsd:5,marginUsd:7}),5);
  assert.equal(verifiedClosedTradeMargin({executedMarginUsd:null,marginUsd:7}),7);
});
test("duration uses original open and actual close, not DCA",()=>{
  assert.equal(closedTradeDurationMs({openedAt:"2026-10-10T10:00:00Z",closedAt:"2026-10-10T11:15:00Z",dcaAt:"2026-10-10T11:00:00Z"}),4500000);
  assert.equal(closedTradeDurationMs({closedAt:"2026-10-10T11:15:00Z"}),null);
});
test("stable newest-first results do not duplicate across pages",()=>{
 const a={exchangeTradeId:"a",closedAt:"2026-10-10T10:00:00Z"},b={exchangeTradeId:"b",closedAt:"2026-10-10T11:00:00Z"};
 assert.deepEqual(uniqueClosedTrades([a,b,b]).map(x=>x.exchangeTradeId),["b","a"]);
 assert.ok(closedTradeTime(b)>closedTradeTime(a));
});
