import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const bridge=readFileSync(new URL("../components/aster-profit-lock-ladder-bridge.tsx",import.meta.url),"utf8");
const card=readFileSync(new URL("../components/aster-extreme-spike-entry-card.tsx",import.meta.url),"utf8");
test("Extreme Spike card is actually mounted in the existing settings portal",()=>{
 assert.match(bridge,/createPortal\(<div className="pll-bridge-wrap"/);
 assert.match(bridge,/<AsterExtremeSpikeEntryCard mode=\{entryMode\}/);
 assert.match(bridge,/onChange=\{\(next\)=>void updateEntryFilter\(next\)\}/);
});
test("all spike levels and 6 timeframes are offered",()=>{
 for(const value of ["2-3","3-4","4-5","5-6","6-7","7+","1m","5m","15m","1h","4h","1d"]){
   assert.ok(card.includes(JSON.stringify(value)),value+" missing");
 }
});
test("only one authoritative filter mode selector",()=>{
 for(const value of ["OFF","BOLLINGER","EXTREME_SPIKE"])assert.ok(card.includes(JSON.stringify(value)));
 assert.match(bridge,/entryMode === "BOLLINGER" \? <AsterBollingerEntryFilter15mCard/);
});
