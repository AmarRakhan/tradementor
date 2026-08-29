import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
const maker=readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
const cockpit=readFileSync(new URL("../components/aster-recent-trades.tsx",import.meta.url),"utf8");
const chart=readFileSync(new URL("../components/trading-chart.tsx",import.meta.url),"utf8");
const markers=readFileSync(new URL("../lib/trade-marker-layout.ts",import.meta.url),"utf8");
test("simple Focus 2.0 wizard stays five steps and exposes configurable harvest",()=>{
  const block=maker.slice(maker.indexOf(" const focusSteps=["),maker.indexOf(" const steps=",maker.indexOf(" const focusSteps=[")));
  assert.equal([...block.matchAll(/title:\"[1-5] ·/g)].length,5);
  assert.match(block,/5 · Winst afromen & controle/);
  assert.match(block,/Winsttrigger \(USDT\)/);
  assert.match(block,/Winst afromen \(USDT\)/);
  assert.doesNotMatch(block,/LONG sluiten bij netto winst/);
});
test("step 4 exposes hard trailing hedge-release controls",()=>{
  assert.match(maker,/Maximale hedge \(%\)/);
  assert.match(maker,/Hedge release-afstand \(%\)/);
  assert.doesNotMatch(maker,/Herstel vanaf recente low \(%\)/);
  assert.doesNotMatch(maker,/Re-hedge terugval \(%\)/);
  assert.match(maker,/Geavanceerde protection-instellingen/);
  assert.match(maker,/advanced:false/);
});
test("simple cockpit shows harvest progress and no full TP label",()=>{
  assert.match(cockpit,/Winst sinds harvest/);
  assert.match(cockpit,/Nog tot afromen/);
  assert.match(cockpit,/Laatste \/ totaal afgeroomd/);
  assert.doesNotMatch(cockpit,/simple\?\"LONG Take Profit\"/);
});
test("chart can render a partial harvest marker distinct from close",()=>{
  assert.match(markers,/\"harvest\"/);
  assert.match(chart,/one\?\.kind===\"harvest\"\?\"HARVEST\"/);
});
