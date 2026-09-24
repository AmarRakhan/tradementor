import assert from "node:assert/strict";
import test from "node:test";
import { buildStrategyStatusCommandCenter, mergeSoldierActivityHistory, parsePortfolioMoney, soldierOpenEventsFromManagedPositions, summarizeSoldierActivity } from "../lib/strategy-status-command-center.mjs";

test("localized Available from Portfolio Snapshot parses without inventing a second reserve",()=>{
  assert.equal(parsePortfolioMoney("US$ 64,25"),64.25);
  assert.equal(parsePortfolioMoney("US$ 1.234,56"),1234.56);
  assert.equal(parsePortfolioMoney("—"),null);
});

test("active soldier truth is always Snapshot LONG plus SHORT",()=>{
  const vm=buildStrategyStatusCommandCenter({actualLong:"78",actualShort:"37",totalActive:113,availableText:"US$ 64,25"});
  assert.equal(vm.totalActiveSoldiers,115);
  assert.equal(vm.actualLong,78);
  assert.equal(vm.actualShort,37);
});

test("extra soldiers and DCA runway are calculated from live Available and current sizing",()=>{
  const vm=buildStrategyStatusCommandCenter({
    actualLong:78,actualShort:37,availableText:"US$ 64,25",
    activeZoneEntryUsd:250,entrySizingMode:"notional",minimumLeverage:50,
    dcaMarginUsd:8,maxDca:8,
  });
  assert.equal(vm.estimatedSoldierCost,5);
  assert.equal(vm.estimatedAffordableSoldiers,12);
  assert.equal(vm.estimatedDcaCost,8);
  assert.equal(vm.estimatedDcaRounds,8);
  assert.equal(vm.dcaCoveragePercent,100);
});

test("no hardcoded sample soldier cost is used",()=>{
  const a=buildStrategyStatusCommandCenter({availableText:"US$ 64,25",activeZoneEntryUsd:250,entrySizingMode:"notional",minimumLeverage:50});
  const b=buildStrategyStatusCommandCenter({availableText:"US$ 64,25",activeZoneEntryUsd:300,entrySizingMode:"notional",minimumLeverage:50});
  assert.equal(a.estimatedSoldierCost,5);
  assert.equal(b.estimatedSoldierCost,6);
  assert.notEqual(a.estimatedAffordableSoldiers,b.estimatedAffordableSoldiers);
});

test("desired action distinguishes desired from actually executable automatic action",()=>{
  const base={
    strategyEnabled:true,zoneSafe:true,activeZone:-1,pendingSide:"LONG",pendingCount:4,
    balancerSide:"LONG",balancerDesired:4,balancerOpen:0,balancerFree:4,
    zoneFreeLong:0,zoneFreeShort:0,availableText:"US$ 64,25",
    activeZoneEntryUsd:250,entrySizingMode:"notional",minimumLeverage:50,
  };
  const executable=buildStrategyStatusCommandCenter(base);
  assert.equal(executable.actionTitle,"+4 LONG automatisch");
  assert.equal(executable.actionExecutable,true);

  const poor=buildStrategyStatusCommandCenter({...base,availableText:"US$ 10,00",activeZoneEntryUsd:250,entrySizingMode:"margin"});
  assert.equal(poor.actionTitle,"Geblokkeerd — onvoldoende available");
  assert.equal(poor.actionExecutable,false);

  const noSeats=buildStrategyStatusCommandCenter({...base,balancerFree:0});
  assert.equal(noSeats.actionTitle,"Geblokkeerd — geen vrije stoelen");
  assert.equal(noSeats.actionExecutable,false);
});

test("strategy off can never claim the bot buys automatically",()=>{
  const vm=buildStrategyStatusCommandCenter({
    strategyEnabled:false,zoneSafe:true,pendingSide:"LONG",pendingCount:4,balancerFree:4,
    availableText:"US$ 100,00",activeZoneEntryUsd:5,entrySizingMode:"margin",
  });
  assert.equal(vm.actionExecutable,false);
  assert.equal(vm.actionTitle,"Geblokkeerd — strategy uit");
  assert.match(vm.footerTitle,/Strategie staat uit/i);
});

test("zone inventory is active-zone capacity and includes active balancer free seats",()=>{
  const vm=buildStrategyStatusCommandCenter({
    baseLong:3,baseShort:3,zoneFreeLong:2,zoneFreeShort:1,
    balancerDesired:4,balancerOpen:1,balancerFree:3,
  });
  assert.equal(vm.freeZoneSeats,6);
  assert.equal(vm.totalZoneSeats,10);
});

test("health thresholds are deterministic and runway based",()=>{
  const ample=buildStrategyStatusCommandCenter({availableText:"US$ 100,00",dcaMarginUsd:10,actualLong:1,actualShort:1});
  const tight=buildStrategyStatusCommandCenter({availableText:"US$ 10,00",dcaMarginUsd:10,actualLong:1,actualShort:1});
  assert.equal(ample.healthState,"RUIM");
  assert.equal(tight.healthState,"KRAP");
});


test("soldier activity extracts only confirmed zone-owned opened positions and ignores non-soldier or recovered rows",()=>{
  const events=soldierOpenEventsFromManagedPositions({
    "BTCUSDT|LONG":{cycleStartedAtMs:1_000_000,soldierId:"s1",soldierRole:"ZONE_BASE",originZone:-1,dcaCount:4},
    "ETHUSDT|SHORT":{cycleStartedAtMs:1_010_000,soldierId:"s2",soldierRole:"EXPOSURE_BALANCER",originZone:-1},
    "SOLUSDT|LONG":{cycleStartedAtMs:1_020_000,cycleId:"legacy",dcaCount:2},
    "XRPUSDT|LONG":{cycleStartedAtMs:1_030_000,soldierId:"recover",soldierRole:"ZONE_BASE",recoveredFromSelectedOpenPosition:true},
  });
  assert.equal(events.length,2);
  assert.deepEqual(events.map((row)=>row.id),["s2:1010000","s1:1000000"]);
  assert.equal(events[0].side,"SHORT");
  assert.equal(events[1].side,"LONG");
  assert.equal(events[1].originZone,-1);
});

test("15m 1u 4u and 24u soldier activity counts LONG and SHORT separately with grouped counts",()=>{
  const now=10_000_000;
  const events=[
    {id:"a",atMs:now-5*60_000,side:"LONG",count:2,originZone:-1},
    {id:"b",atMs:now-30*60_000,side:"SHORT",count:1,originZone:-1},
    {id:"c",atMs:now-2*60*60_000,side:"LONG",count:3,originZone:-2},
    {id:"d",atMs:now-8*60*60_000,side:"SHORT",count:4,originZone:0},
    {id:"old",atMs:now-25*60*60_000,side:"LONG",count:99,originZone:0},
  ];
  const summary=summarizeSoldierActivity(events,now);
  assert.deepEqual(summary.windows["15m"],{key:"15m",label:"15m",long:2,short:0,total:2});
  assert.deepEqual(summary.windows["1u"],{key:"1u",label:"1u",long:2,short:1,total:3});
  assert.deepEqual(summary.windows["4u"],{key:"4u",label:"4u",long:5,short:1,total:6});
  assert.deepEqual(summary.windows["24u"],{key:"24u",label:"24u",long:5,short:5,total:10});
});

test("recent soldier activity is newest-first and limited to three confirmed openings",()=>{
  const now=20_000_000;
  const summary=summarizeSoldierActivity([
    {id:"1",atMs:now-4_000,side:"LONG",count:1},
    {id:"2",atMs:now-1_000,side:"SHORT",count:2},
    {id:"3",atMs:now-3_000,side:"LONG",count:3},
    {id:"4",atMs:now-2_000,side:"SHORT",count:4},
  ],now);
  assert.deepEqual(summary.recent.map((row)=>row.id),["2","4","3"]);
});

test("activity history keeps confirmed openings after a soldier later disappears from the current managed set",()=>{
  const now=30_000_000;
  const first=mergeSoldierActivityHistory([],[
    {id:"soldier-1",atMs:now-1_000,side:"LONG",count:1,originZone:-1},
  ],now);
  const afterClose=mergeSoldierActivityHistory(first,[],now+60_000);
  assert.equal(afterClose.length,1);
  assert.equal(afterClose[0].id,"soldier-1");
});

test("current active soldier total remains independent from historical activity totals",()=>{
  const now=40_000_000;
  const vm=buildStrategyStatusCommandCenter({
    actualLong:77,actualShort:37,totalActive:999,
    soldierActivity:[
      {id:"a",atMs:now-1_000,side:"LONG",count:3},
      {id:"b",atMs:now-2_000,side:"SHORT",count:2},
    ],
    nowMs:now,
  });
  assert.equal(vm.totalActiveSoldiers,114);
  assert.equal(vm.soldierActivity.windows["15m"].total,5);
});
