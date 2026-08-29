import test from "node:test";
import assert from "node:assert/strict";
import { applyAsterRealtimeMark, parseSseChunk } from "../lib/aster-realtime.mjs";

test("live mark updates only matching position and recalculates PnL", () => {
  const source={positions:[{symbol:"SOLUSDT",side:"LONG",quantity:2,entryPrice:100,markPrice:100,unrealizedPnl:0},{symbol:"BTCUSDT",side:"SHORT",quantity:1,entryPrice:50,markPrice:50,unrealizedPnl:0}]};
  const out=applyAsterRealtimeMark(source,{symbol:"SOLUSDT",markPrice:103,receivedAtMs:10,transportLatencyMs:4});
  assert.equal(out.positions[0].markPrice,103);assert.equal(out.positions[0].unrealizedPnl,6);assert.equal(out.positions[0].notionalUsd,206);
  assert.equal(out.positions[1],source.positions[1]);assert.equal(out.unrealizedPnl,6);assert.equal(source.positions[0].markPrice,100);
});
test("short PnL uses inverse price direction",()=>{const out=applyAsterRealtimeMark({positions:[{symbol:"X",side:"SHORT",quantity:2,entryPrice:10}]},{symbol:"X",markPrice:8});assert.equal(out.positions[0].unrealizedPnl,4)});
test("SSE parser preserves split frames",()=>{const a=parseSseChunk('', 'event: mark\ndata: {"symbol":"SOL');const b=parseSseChunk(a.rest,'USDT","markPrice":101}\n\n');assert.equal(b.events[0].symbol,'SOLUSDT');assert.equal(b.events[0].markPrice,101)});
