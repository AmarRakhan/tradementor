import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const component=fs.readFileSync(new URL("../components/aster-strategy3-control.tsx",import.meta.url),"utf8");
const performance=fs.readFileSync(new URL("../components/aster-performance-panel.tsx",import.meta.url),"utf8");

test("Strategy 3 is separately visible and paper-only",()=>{
  assert.match(component,/Dual Harvest Adaptive Shield/);
  assert.match(component,/LIVE GEBLOKKEERD/);
  assert.match(component,/mode:\"paper\"/);
  assert.doesNotMatch(component,/strategy3\/start/);
  assert.match(performance,/AsterStrategy3Control/);
});

test("paper simulator stays local and cannot place live orders",()=>{
  const route=fs.readFileSync(new URL("../app/api/exchanges/aster/strategy3/simulate/route.ts",import.meta.url),"utf8");
  const engine=fs.readFileSync(new URL("../lib/aster-strategy3-paper.ts",import.meta.url),"utf8");
  assert.match(route,/simulateStrategy3Paper/);
  assert.doesNotMatch(route,/proxyCloud/);
  assert.match(engine,/paperOnly:true,liveReady:false/);
  assert.doesNotMatch(engine,/fetch\(/);
});
