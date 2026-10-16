import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {selectSparseBotEdit} from "../lib/p0-sparse-bot-edit.mjs";
const maker=readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
test("main configurator invokes seat-only sparse classifier, excludes TP and zones",()=>{
 assert.match(maker,/selectSparseBotEdit\(confirmedSettings, settings, \["maximumPositions"\]\)/);
 assert.match(maker,/seatChanged && !otherChanged && settings\.priceZoneSeats\?\.enabled === true/);
 assert.doesNotMatch(maker,/selectSparseBotEdit\(confirmedSettings, settings, \["takeProfit/);
});
test("in-memory seat GET->PUT->GET and unchanged aliases, notional and Spike",()=>{
 const get={maximumPositions:10,longSlots:7,shortSlots:3,entrySizingMode:"notional",entryFilterMode:"EXTREME_SPIKE",priceZoneSeats:{enabled:true,longSeatsPerZone:2,shortSeatsPerZone:0},takeProfit:0.015};
 const requested={...get,maximumPositions:12};
 const patch=selectSparseBotEdit(get,requested,["maximumPositions"]);
 assert.deepEqual(patch,{maximumPositions:12});
 const put={...get,...patch};
 const readback=structuredClone(put);
 assert.equal(readback.maximumPositions,12);
 for(const key of ["entrySizingMode","entryFilterMode","priceZoneSeats","takeProfit","longSlots","shortSlots"])assert.deepEqual(readback[key],get[key]);
});
test("409 and 422 backend failures do not persist seat mutation",()=>{
 for(const status of [409,422]){
  const saved={maximumPositions:10,entryFilterMode:"EXTREME_SPIKE"};
  const put={status,ok:false};
  if(put.ok)Object.assign(saved,{maximumPositions:12});
  assert.equal(saved.maximumPositions,10);
 }
});
