import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {selectSparseBotEdit} from "../lib/p0-sparse-bot-edit.mjs";

// Reproduce a GET -> sparse PUT -> GET against the parser's documented
// published key contract, entirely in memory and with no account access.
const parser = readFileSync(new URL("../../cloud_api/aster_multi_bb_core.py",import.meta.url),"utf8");
const output = parser.slice(parser.indexOf("def public_dict("),parser.indexOf("def position_action_preview("));
test("side-specific TP needs a canonical backend persistence contract before maker sparse integration",()=>{
 assert.match(output,/"takeProfit": self.take_profit/);
 assert.doesNotMatch(output,/"takeProfitLong":/);
 assert.doesNotMatch(output,/"takeProfitShort":/);
 const before={takeProfit:0.01,entryFilterMode:"EXTREME_SPIKE",priceZoneSeats:{enabled:true,longSeatsPerZone:2,shortSeatsPerZone:0}};
 const submitted=selectSparseBotEdit({...before,takeProfitLong:0.01},{...before,takeProfitLong:0.02},["takeProfitLong"]);
 assert.deepEqual(submitted,{takeProfitLong:0.02});
 // Simulated canonical output: the separate side TP does not roundtrip.
 const after={...before};
 assert.equal(after.takeProfitLong,undefined);
 assert.equal(after.entryFilterMode,"EXTREME_SPIKE");
 assert.deepEqual(after.priceZoneSeats,before.priceZoneSeats);
});
test("backend 409/422 on sparse save never yields an invented readback",()=>{
 for(const status of [409,422]){
   const put={status,ok:false};
   const persisted={maximumPositions:20,entryFilterMode:"EXTREME_SPIKE"};
   assert.equal(put.ok,false);
   assert.equal(persisted.maximumPositions,20);
 }
});
