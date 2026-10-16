import test from "node:test";
import assert from "node:assert/strict";
import {selectSparseBotEdit} from "../lib/p0-sparse-bot-edit.mjs";
const old={takeProfit:0.01,takeProfitLong:0.01,longTakeProfitValue:0.01,takeProfitShort:0.01,shortTakeProfitValue:0.01,maximumPositions:20,longSlots:15,shortSlots:5,entryFilterMode:"EXTREME_SPIKE",priceZoneSeats:{enabled:true,longSeatsPerZone:2,shortSeatsPerZone:0}};
test("TP edit selects only supplied, explicitly edited TP field",()=>{
 const next={...old,takeProfitLong:0.02};
 assert.deepEqual(selectSparseBotEdit(old,next,["takeProfitLong"]),{takeProfitLong:0.02});
 assert.equal(old.entryFilterMode,"EXTREME_SPIKE");
 assert.equal(old.priceZoneSeats.shortSeatsPerZone,0);
});
test("seat edit selects intended single seat field without zone mutation",()=>{
 assert.deepEqual(selectSparseBotEdit(old,{...old,maximumPositions:25},["maximumPositions"]),{maximumPositions:25});
});
test("explicit Spike or zone change never takes sparse path",()=>{
 assert.equal(selectSparseBotEdit(old,{...old,entryFilterMode:"OFF"},["entryFilterMode"]),null);
 assert.equal(selectSparseBotEdit(old,{...old,priceZoneSeats:{enabled:false}},["priceZoneSeats"]),null);
});
test("missing saved alias and non-finite input fail closed",()=>{
 assert.equal(selectSparseBotEdit({}, {takeProfitLong:0.02},["takeProfitLong"]),null);
 assert.equal(selectSparseBotEdit(old,{...old,takeProfitLong:NaN},["takeProfitLong"]),null);
});
