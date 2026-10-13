import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const route = readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts", import.meta.url), "utf8");
const bridge = readFileSync(new URL("../components/aster-profit-lock-ladder-bridge.tsx", import.meta.url), "utf8");

test("legacy editor preserves all four canonical Spike settings",()=>{
 for(const field of ["entryFilterMode","extremeSpikeLevel","extremeSpikeLongTimeframe","extremeSpikeShortTimeframe"]){
   assert.match(route,new RegExp('"' + field + '"'));
 }
});
test("legacy editor cannot reenable Bollinger over existing Spike mode",()=>{
 assert.match(route,/current\.entryFilterMode === "EXTREME_SPIKE"/);
 assert.match(route,/merged\.bollingerEntryFilter15mEnabled = false/);
});
test("Spike UI persists mutually exclusive mode with immediate server readback",()=>{
 assert.match(bridge,/entryFilterMode:next\.mode/);
 assert.match(bridge,/bollingerEntryFilter15mEnabled:next\.mode==="BOLLINGER"/);
 assert.match(bridge,/saved\.entryFilterMode!==next\.mode/);
 assert.match(bridge,/setEntryMode\(next\.mode\)/);
});
test("old Bollinger UI is displayed only in Bollinger mode",()=>{
 assert.match(bridge,/entryMode === "BOLLINGER" \? <AsterBollingerEntryFilter15mCard/);
});

test("legacy save fails closed if current Spike mode cannot be verified",()=>{
 assert.match(route,/const missingSpikeMode = !Object\.prototype\.hasOwnProperty\.call\(settingsRecord, "entryFilterMode"\)/);
 assert.match(route,/status:409/);
 assert.match(route,/if \(!status\.ok\) return missingSpikeMode \? safeFailure\(\) : request/);
 assert.match(route,/if \(preserved instanceof Response\) return preserved/);
});

test("Spike save confirms independent GET readback, not merely PUT echo",()=>{
 assert.match(bridge,/const readbackSnapshot = await authenticatedRequest\("\/api\/exchanges\/aster", \{cache:"no-store"\}\)/);
 assert.match(bridge,/const readback = extract\(readbackSnapshot\)\.settings/);
 assert.match(bridge,/readback\.entryFilterMode!==next\.mode/);
 assert.match(bridge,/readback\.extremeSpikeShortTimeframe!==next\.shortTimeframe/);
 assert.match(bridge,/setSettings\(readback\);setEntryMode\(next\.mode\)/);
});
