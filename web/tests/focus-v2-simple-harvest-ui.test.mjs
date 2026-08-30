import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
const maker=readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
const cockpit=readFileSync(new URL("../components/aster-recent-trades.tsx",import.meta.url),"utf8");
const chart=readFileSync(new URL("../components/trading-chart.tsx",import.meta.url),"utf8");
const markers=readFileSync(new URL("../lib/trade-marker-layout.ts",import.meta.url),"utf8");
test("simple Focus 2.0 wizard stays five steps and exposes configurable full TP",()=>{
  const block=maker.slice(maker.indexOf(" const focusSteps=["),maker.indexOf(" const steps=",maker.indexOf(" const focusSteps=[")));
  assert.equal([...block.matchAll(/title:\"[1-5] ·/g)].length,5);
  assert.match(block,/5 · Full Take Profit & auto-herstart/);
  assert.match(block,/Take Profit modus/);
  assert.match(block,/Take Profit \(\$ \/ USDT\)/);
  assert.match(block,/Na Take Profit direct opnieuw starten/);
  assert.doesNotMatch(block,/Winsttrigger \(USDT\)/);
});
test("step 4 exposes exact total-long hedge target and last-DCA release",()=>{
  assert.match(maker,/Hedge target \(% van totale LONG\)/);
  assert.match(maker,/SHORT volledig los na herstel \(%\)/);
  assert.match(maker,/alleen het ontbrekende SHORT-notional/);
  assert.match(maker,/Overhedging is niet toegestaan/);
  assert.doesNotMatch(maker,/Re-hedge terugval \(%\)/);
});
test("v6 cockpit shows full TP and cycle protection state",()=>{
  assert.match(cockpit,/Cycle status/);
  assert.match(cockpit,/Starthedge/);
  assert.match(cockpit,/Hedge target/);
  assert.match(cockpit,/Take Profit/);
  assert.match(cockpit,/Nog tot TP/);
  assert.match(cockpit,/Auto-herstart/);
});
test("chart can render a partial harvest marker distinct from close",()=>{
  assert.match(markers,/\"harvest\"/);
  assert.match(chart,/one\?\.kind===\"harvest\"\?\"HARVEST\"/);
});

test("v5 chart uses compact non-blocking future trigger presentation",()=>{
  assert.match(chart,/const addSegment=/);
  assert.match(chart,/DCA \/ SHORT SYNC/);
  assert.match(chart,/SHORT RELEASE/);
  assert.doesNotMatch(chart,/stateVersion>=5[^\n]*RE-HEDGE/);
});
test("v5 cockpit hides armed rehedge copy and names both active trigger directions",()=>{
  assert.match(cockpit,/v5\?"":` · armed/);
  assert.match(cockpit,/VOLGENDE DCA \+ SHORT BIJKOPEN/);
  assert.match(cockpit,/SHORT VOLLEDIG LOSLATEN/);
});
