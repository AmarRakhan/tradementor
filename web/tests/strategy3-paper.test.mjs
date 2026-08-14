import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const component=fs.readFileSync(new URL("../components/aster-strategy3-control.tsx",import.meta.url),"utf8");
const performance=fs.readFileSync(new URL("../components/aster-performance-panel.tsx",import.meta.url),"utf8");

test("Strategy 3 exposes only the isolated confirmed live runtime",()=>{
  assert.match(component,/Dual Harvest Adaptive Shield/);
  assert.match(component,/Strategy 3 live bot/);
  assert.match(component,/GEÏSOLEERDE LIVE RUNTIME/);
  assert.match(component,/Controleer live-gereedheid · geen order/);
  assert.match(component,/mode:\"paper\"\|\"live\"/);
  assert.match(component,/checkReadiness/);
  assert.match(component,/confirmLive/);
  assert.match(component,/confirmedSettings=payload\("live"\)/);
  assert.doesNotMatch(component,/buildPayload\(defaults,"live"\)/);
  assert.match(component,/Protected Trailing \{draft\.trailing/);
  assert.match(component,/Start Strategy 3 nu live/);
  assert.doesNotMatch(component,/Start geblokkeerd/);
  assert.match(component,/Strategy 3 live is gestart/);
  assert.match(component,/geen snelle opbouw/);
  assert.match(performance,/AsterStrategy3Control/);
  assert.doesNotMatch(performance,/AsterStrategy3RapidBuild|rapid-build/);
});

test("paper simulator stays local and cannot place live orders",()=>{
  const route=fs.readFileSync(new URL("../app/api/exchanges/aster/strategy3/simulate/route.ts",import.meta.url),"utf8");
  const engine=fs.readFileSync(new URL("../lib/aster-strategy3-paper.ts",import.meta.url),"utf8");
  assert.match(route,/simulateStrategy3Paper/);
  assert.doesNotMatch(route,/proxyCloud/);
  assert.match(engine,/paperOnly:true,liveReady:false/);
  assert.doesNotMatch(engine,/fetch\(/);
});
