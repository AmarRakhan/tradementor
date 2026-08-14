import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const read=(path)=>readFile(new URL(`../${path}`,import.meta.url),"utf8");
test("staging is default and production is explicit",async()=>{const source=await read("lib/cloud-proxy.ts");assert.match(source,/TRADEMENTOR_DEPLOYMENT_MODE \?\? "staging"/);assert.match(source,/mode !== "production"/);assert.doesNotMatch(source,/tradementor-api-604335232956/)});
test("risk actions are blocked",async()=>{const source=await read("lib/staging-backend.ts");for(const term of ["canary","rapid-build","execution\\/live","credentials","ordersEnabled:false"])assert.ok(source.includes(term),`missing ${term}`)});
test("Firebase identity stays pinned",async()=>{const source=await read("lib/staging-auth.ts");assert.match(source,/tradementor-production/);assert.match(source,/securetoken\.google\.com/)});
test("persistence is uid scoped",async()=>{const source=await read("lib/staging-db.ts");assert.match(source,/UNIQUE\(uid,key\)/);assert.match(source,/UNIQUE\(uid,strategy_id\)/)});

test("read-only compatibility mode can load existing data but cannot write upstream",async()=>{
  const source=await read("lib/cloud-proxy.ts");
  assert.match(source,/mode === "read-only" && method === "GET"/);
  assert.match(source,/isApprovedReadPath\(pathname\)/);
  assert.match(source,/READ_ONLY_PATHS/);
  assert.doesNotMatch(source,/mode === "read-only" && method !== "GET"/);
  assert.match(source,/return stagingProxy\(request, pathname, method, bodyOverride\)/);
});
test("staging settings shadow production reads per Firebase uid",async()=>{
  const [proxy,db]=await Promise.all([read("lib/cloud-proxy.ts"),read("lib/staging-db.ts")]);
  assert.match(proxy,/requireStagingIdentity\(request\)/);
  assert.match(proxy,/getStrategyOverride\(identity\.uid/);
  assert.match(proxy,/getPreference\(identity\.uid/);
  assert.match(proxy,/existing-read-plus-staging-shadow/);
  assert.match(proxy,/ordersEnabled: false/);
  assert.match(proxy,/liveEnabled: false/);
  assert.match(db,/WHERE uid=\? AND strategy_id=\?/);
  assert.match(db,/if\(!row\)return null/);
});
test("Strategy 2 production proxy is narrowly scoped and preserves Firebase identity",async()=>{
  const [maker,proxy,start,readiness]=await Promise.all([read("components/aster-strategy2-maker.tsx"),read("lib/secure-strategy2-live.ts"),read("app/api/exchanges/aster/strategy2/start/route.ts"),read("app/api/exchanges/aster/strategy2/readiness/route.ts")]);
  assert.match(maker,/const paperOnly=false/);
  assert.match(proxy,/const strategy2Paths = new Set/);
  assert.match(proxy,/authorization\?\.startsWith\("Bearer "\)/);
  assert.match(proxy,/Authorization: authorization/);
  assert.match(proxy,/CLOUD_API_URL/);
  assert.match(start,/proxyStrategy2Live/);
  assert.match(readiness,/proxyStrategy2Live/);
});
test("Strategy 2 live controls cannot bypass server readiness or create request loops",async()=>{
  const maker=await read("components/aster-strategy2-maker.tsx");
  assert.match(maker,/if\(state\.liveReady\)\{await action\("start-live"\)/);
  assert.match(maker,/await checkReadiness\(\)/);
  assert.match(maker,/result\.started!==true/);
  assert.match(maker,/geen extra startopdrachten verzonden/);
  assert.match(maker,/Boolean\(readiness\?\.softwareReady\)/);
});
test("Strategy 3 remains authenticated paper-only",async()=>{const source=await read("app/api/exchanges/aster/strategy3/simulate/route.ts");assert.match(source,/requireStagingIdentity/);assert.match(source,/ordersEnabled:false/);assert.match(source,/ordersPlaced:0/)});
test("Strategy 3 paper status survives a full app restart",async()=>{const [backend,proxy,db]=await Promise.all([read("lib/staging-backend.ts"),read("lib/cloud-proxy.ts"),read("lib/staging-db.ts")]);assert.match(backend,/s3\.status==="paper-active"\?"PAPER":"STOPPED"/);assert.match(backend,/strategy3:\{enabled:false,phase:"PAPER"/);assert.match(backend,/strategy3:\{enabled:false,phase:"STOPPED"/);assert.match(proxy,/strategy3\.status === "paper-active" \? "PAPER" : "STOPPED"/);assert.match(db,/ON CONFLICT\(uid,strategy_id\) DO UPDATE/);assert.match(db,/status=excluded\.status/);});
test("Strategy 3 shadow never leaks stale production scheduler state",async()=>{const source=await read("lib/cloud-proxy.ts");assert.match(source,/Paper Mode actief · beslissingen worden gesimuleerd · 0 echte orders/);assert.match(source,/strategy3: strategy3 \? \{ \.\.\.upstreamStrategy3, enabled: false/);});
