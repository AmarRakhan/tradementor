import test from "node:test";
import assert from "node:assert/strict";
import { normalizeAsterAccountTruth } from "../lib/aster-account-truth.ts";

function payload(positions) {
  const longCount=positions.filter((row)=>row.side==="LONG").length;
  const shortCount=positions.filter((row)=>row.side==="SHORT").length;
  return {accountTruth:{
    schemaVersion:1,contract:"ASTER_ACCOUNT_TRUTH_V1",source:"ASTER_SERVER_CANONICAL_STATUS",
    capturedAtMs:Date.now(),stale:false,configured:true,readOnly:true,ordersSent:0,
    account:{equity:300,availableBalance:200},
    positions:{count:positions.length,longCount,shortCount,rows:positions},
    performance:{closedTodayReliable:false,growthReliable:false},
    strategy:{settings:{},runtimeTruth:{},summary:{enabled:true,monitor:false,activeLong:longCount,activeShort:shortCount,longCapacity:2,shortCapacity:1,dcaCount:0,phase:"RUNNING"}},
    provenance:{},
  }};
}

test("canonical server positions contract owns active position count",()=>{
  const truth=normalizeAsterAccountTruth(payload([
    {symbol:"ZECUSDT",side:"SHORT",quantity:1},
    {symbol:"ETHUSDT",side:"LONG",quantity:2},
  ]));
  assert.equal(truth.positions.count,2);
  assert.equal(truth.positions.longCount,1);
  assert.equal(truth.positions.shortCount,1);
});

test("frontend position count has no legacy cache merge or scalar canonicalization",()=>{
  const truth=normalizeAsterAccountTruth(payload([{symbol:"ETHUSDT",side:"LONG",quantity:2}]));
  assert.equal(truth.positions.count,1);
  assert.equal(truth.positions.rows.length,1);
});
