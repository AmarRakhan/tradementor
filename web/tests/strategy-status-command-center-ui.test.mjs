import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("new Command Center remains hard betaOwner-only while non-owner keeps existing cockpit",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("const { user, betaOwner }=useAuthSession()"));
  assert.ok(component.includes("const commandCenterTester=betaOwner===true"));
  assert.ok(component.includes("commandCenterTester&&"));
  assert.ok(component.includes("!commandCenterTester&&"));
  assert.ok(component.includes("portfolio-strategy-cockpit"));
});

test("Build 432 owner Command Center uses the current screenshot reference and live-state labels",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes('data-reference="file_00000000cf9481f4b495250734661e31"'));
  for(const label of ["ACTIEVE ZONE","NETTO EXPOSURE","ZONE-SOLDATEN ACTIEF","OUDE-ZONE POSITIES","WINST THUISGEKOMEN","VOLGENDE ZONES"]){
    assert.ok(component.includes(label),label);
  }
  for(const removed of ["THUIS / BESCHIKBAAR","VOLGENDE MOGELIJKE INSTROOM","<small>ENTRY-PRIORITEIT</small>"]){
    assert.equal(component.includes(removed),false,removed);
  }
});

test("owner Command Center removes mutation controls and duplicate balancer/free-seat emphasis",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const start=component.indexOf("function StrategyCommandCenter");
  const end=component.indexOf("export function PortfolioKoersChart",start);
  const block=component.slice(start,end);
  assert.equal(block.includes('method:"PUT"'),false);
  assert.equal(block.includes('method:"POST"'),false);
  assert.equal(block.includes("onClick"),false);
  assert.equal(block.includes("THUIS / BESCHIKBAAR"),false);
  assert.equal(block.includes("VOLGENDE MOGELIJKE INSTROOM"),false);
});

test("Command Center receives exact strategy-owned counts, old-zone subset, exposure and zone boundaries",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  for(const token of [
    "strategyOwnedTotal","strategyOwnedLong","strategyOwnedShort",
    "currentZoneOwnedLong","currentZoneOwnedShort",
    "oldZonesOpenTotal:oldOpenTotal","oldZonesOpenLong:oldOpenLong","oldZonesOpenShort:oldOpenShort",
    "netExposureUsd","netExposureSide","nextZone:nextUpIndex","previousZone:nextDownIndex",
  ]) assert.ok(component.includes(token),token);
});

test("Build 432 mobile status grid is two-column and overflow-safe",async()=>{
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(css.includes(".pcc-status-grid-v2{grid-template-columns:repeat(2,minmax(0,1fr))!important}"));
  assert.ok(css.includes("overflow-wrap:anywhere"));
  assert.ok(css.includes("@media(max-width:380px)"));
});

test("existing advisor refresh remains no faster than 45 seconds while live markers use their own lightweight feed",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const advisorStart=component.indexOf("const loadAdvisor=useCallback");
  const liveEventStart=component.indexOf("const loadRecentEvents=useCallback",advisorStart);
  const advisorBlock=component.slice(advisorStart,liveEventStart);
  assert.ok(advisorBlock.includes("},45_000);"));
  assert.ok(component.includes("/api/exchanges/aster/portfolio-chart/events?timeframe="));
  assert.ok(component.includes("},5_000);"));
});
