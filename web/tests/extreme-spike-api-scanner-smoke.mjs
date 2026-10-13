import {readFileSync} from "node:fs";
import {spawnSync} from "node:child_process";
import ts from "typescript";
const source=readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts",import.meta.url),"utf8");
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const settings={universeTopN:1,maximumPositions:1,longSlots:1,shortSlots:0,minimumLeverage:20,maximumLeverage:20,entryFilterMode:"EXTREME_SPIKE",bollingerEntryFilter15mEnabled:false,extremeSpikeLevel:"5-6",extremeSpikeLongTimeframe:"1m",extremeSpikeShortTimeframe:"15m",priceZoneSeats:{enabled:false,longSeatsPerZone:1,shortSeatsPerZone:0},zoneSoldiersEnabled:false};
let persisted=null;
const mockRequire=name=> {
 if(name==="@/lib/aster-strategy2-settings-guard")return {guardedAsterStrategy2Request:async request=>({request})};
 if(name==="@/lib/secure-strategy2-live")return {proxyStrategy2Live:async request=>{
   persisted=(await request.json()).settings;
   return Response.json({strategy2:{settings:persisted}});
 }};
 throw Error("Unexpected import "+name);
};
const mod={exports:{}};
new Function("require","module","exports","fetch","Request","Response","Headers",js)(
 mockRequire,mod,mod.exports,async()=>Response.json({strategy2:{settings}}),Request,Response,Headers);
const res=await mod.exports.PUT(new Request("https://isolated.invalid/api/exchanges/aster/strategy2/settings",{method:"PUT",headers:{authorization:"Bearer mock-only", "content-type":"application/json"},body:JSON.stringify({settings})}));
if(res.status!==200||!persisted)throw Error("Settings route did not persist test config");
const py=spawnSync("python3",["../cloud_api/aster_spike_api_scanner_smoke.py"],{input:JSON.stringify(persisted),encoding:"utf8",env:{...process.env,PYTHONPATH:"../cloud_api"}});
process.stdout.write(py.stdout||"");process.stderr.write(py.stderr||"");
if(py.status!==0)process.exit(py.status||1);
