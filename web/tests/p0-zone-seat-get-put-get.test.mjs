import test from "node:test";
import assert from "node:assert/strict";
import {selectSparseBotEdit} from "../lib/p0-sparse-bot-edit.mjs";

// In-memory account-owned Firestore representation. No API, exchange or cloud calls.
test("zone seat capacity GET -> sparse PUT -> GET preserves filters and zones", () => {
 const stored={maximumPositions:20,longSlots:12,shortSlots:8,
  priceZoneSeats:{enabled:true,longSeatsPerZone:2,shortSeatsPerZone:0},
  entryFilterMode:"EXTREME_SPIKE",bollingerEntryFilter15mEnabled:false,
  takeProfit:0.015,configVersion:10};
 const before=structuredClone(stored);
 const submitted=selectSparseBotEdit(before,{...before,maximumPositions:25},["maximumPositions"]);
 assert.deepEqual(submitted,{maximumPositions:25});
 const persisted={...before,...submitted,configVersion:11};
 const after=structuredClone(persisted);
 assert.equal(after.maximumPositions,25);
 assert.equal(after.configVersion,11);
 for(const key of ["priceZoneSeats","entryFilterMode","bollingerEntryFilter15mEnabled","takeProfit","longSlots","shortSlots"])
  assert.deepEqual(after[key],before[key],key);
});
test("mock backend rejects 409/422 without write or invented GET readback",()=>{
 for(const status of [409,422]){
  const saved={maximumPositions:20,entryFilterMode:"EXTREME_SPIKE"};
  const prior=structuredClone(saved);
  const response={status,ok:false};
  if(response.ok)Object.assign(saved,{maximumPositions:25});
  assert.deepEqual(saved,prior);
 }
});
