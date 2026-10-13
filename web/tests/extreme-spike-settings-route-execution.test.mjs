import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import ts from "typescript";

// Exercise the actual Next route handler with dependency-injected network adapters.
// This is an isolated request-handler integration test, NOT staging or live API.
const source=readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts",import.meta.url),"utf8");
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;

async function executeRoute({incoming,current,fetchFails=false}){
 let writes=0,lastWrite=null;
 const mockFetch=async()=>fetchFails?new Response("unavailable",{status:503}):
  Response.json({strategy2:{settings:current}});
 const mockRequire=(name)=>{
  if(name==="@/lib/aster-strategy2-settings-guard")return {guardedAsterStrategy2Request:async request=>({request})};
  if(name==="@/lib/secure-strategy2-live")return {proxyStrategy2Live:async request=>{
   writes++;lastWrite=(await request.json()).settings;
   return Response.json({strategy2:{settings:lastWrite}});
  }};
  throw new Error("Unexpected import: "+name);
 };
 const mod={exports:{}};
 const createRoute=new Function("require","module","exports","fetch","Request","Response","Headers",compiled);
 createRoute(mockRequire,mod,mod.exports,mockFetch,Request,Response,Headers);
 const request=new Request("https://isolated.invalid/api/exchanges/aster/strategy2/settings",{
   method:"PUT",headers:{"authorization":"Bearer test-token","content-type":"application/json"},
   body:JSON.stringify({settings:incoming})
 });
 const response=await mod.exports.PUT(request);
 return {response,writes,lastWrite};
}

const base={entryFilterMode:"EXTREME_SPIKE",bollingerEntryFilter15mEnabled:false,
 extremeSpikeLevel:"5-6",extremeSpikeLongTimeframe:"1m",extremeSpikeShortTimeframe:"15m",
 takeProfitMode:"PORTFOLIO",portfolioTpValue:0.5,maximumLeverage:20};

test("actual API route retains Spike mode and TP on a legacy settings save",async()=>{
 const result=await executeRoute({incoming:{bollingerEntryFilter15mEnabled:true,maxDca:10},current:base});
 assert.equal(result.response.status,200);
 assert.equal(result.writes,1);
 assert.equal(result.lastWrite.entryFilterMode,"EXTREME_SPIKE");
 assert.equal(result.lastWrite.bollingerEntryFilter15mEnabled,false);
 for(const field of ["extremeSpikeLevel","extremeSpikeLongTimeframe","extremeSpikeShortTimeframe",
                      "takeProfitMode","portfolioTpValue","maximumLeverage"]){
   assert.equal(result.lastWrite[field],base[field],field);
 }
 assert.equal(result.lastWrite.maxDca,10);
});
test("actual API route fails closed without readback and never writes",async()=>{
 const result=await executeRoute({incoming:{bollingerEntryFilter15mEnabled:true},current:base,fetchFails:true});
 assert.equal(result.response.status,409);
 assert.equal(result.writes,0);
});
test("explicit OFF and Bollinger modes are respected by actual API handler",async()=>{
 for(const mode of ["OFF","BOLLINGER"]){
  const result=await executeRoute({incoming:{...base,entryFilterMode:mode,
    bollingerEntryFilter15mEnabled:mode==="BOLLINGER"},current:base});
  assert.equal(result.response.status,200);
  assert.equal(result.lastWrite.entryFilterMode,mode);
  assert.equal(result.lastWrite.bollingerEntryFilter15mEnabled,mode==="BOLLINGER");
 }
});
