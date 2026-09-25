import assert from "node:assert/strict";
import test from "node:test";
import {
  buildStrategyStatusCommandCenter,
  countWinningHomecomingsToday,
  mergeSoldierActivityHistory,
  parsePortfolioMoney,
  soldierOpenEventsFromManagedPositions,
  summarizeSoldierActivity,
} from "../lib/strategy-status-command-center.mjs";

test("localized Available parses correctly",()=>{
  assert.equal(parsePortfolioMoney("US$ 64,25"),64.25);
  assert.equal(parsePortfolioMoney("US$ 1.234,56"),1234.56);
  assert.equal(parsePortfolioMoney("—"),null);
});

test("fixed zone formation is complete capacity and ignores balancer counts",()=>{
  const vm=buildStrategyStatusCommandCenter({
    strategyEnabled:true,zoneSafe:true,activeZone:-1,
    baseLong:3,baseShort:3,zoneOpenLong:2,zoneOpenShort:1,zoneFreeLong:1,zoneFreeShort:2,
    balancerDesired:11,balancerFree:11,entryPriority:"LONG",
    availableText:"US$ 66,67",activeZoneEntryUsd:250,entrySizingMode:"notional",minimumLeverage:50,
    entryBudget:{availableUsd:66.67,requiredInitialMarginUsd:5,safetyBufferUsd:.25,requiredTotalUsd:5.25,shortfallUsd:0,status:"SUFFICIENT"},
  });
  assert.equal(vm.totalZoneSeats,6);
  assert.equal(vm.freeZoneSeats,3);
  assert.equal(vm.entryPriority,"LONG");
  assert.equal(vm.nextPossibleInflow,"1 LONG");
  assert.equal(vm.formationHardCap,true);
  assert.equal("pendingCount" in vm,false);
});

test("priority side cannot create entry when fixed formation has no free soldier",()=>{
  const vm=buildStrategyStatusCommandCenter({
    strategyEnabled:true,zoneSafe:true,baseLong:3,baseShort:3,
    zoneOpenLong:3,zoneOpenShort:1,zoneFreeLong:0,zoneFreeShort:2,
    entryPriority:"LONG",availableText:"US$ 100,00",
    activeZoneEntryUsd:250,entrySizingMode:"notional",minimumLeverage:50,
    entryBudget:{availableUsd:100,requiredInitialMarginUsd:5,safetyBufferUsd:.25,requiredTotalUsd:5.25,shortfallUsd:0,status:"SUFFICIENT"},
  });
  assert.equal(vm.nextPossibleInflow,"GEEN");
  assert.match(vm.nextPossibleDetail,/geen vrije LONG-soldaat/i);
});

test("without exposure priority next entry stays inside free base formation",()=>{
  const vm=buildStrategyStatusCommandCenter({
    strategyEnabled:true,zoneSafe:true,baseLong:3,baseShort:3,
    zoneOpenLong:1,zoneOpenShort:2,zoneFreeLong:2,zoneFreeShort:1,
    availableText:"US$ 100,00",activeZoneEntryUsd:250,entrySizingMode:"notional",minimumLeverage:50,
    entryBudget:{availableUsd:100,requiredInitialMarginUsd:5,safetyBufferUsd:.25,requiredTotalUsd:5.25,shortfallUsd:0,status:"SUFFICIENT"},
  });
  assert.equal(vm.entryPriority,"GEEN");
  assert.equal(vm.nextPossibleInflow,"1 LONG");
});

test("insufficient Available cannot claim next legal inflow",()=>{
  const vm=buildStrategyStatusCommandCenter({
    strategyEnabled:true,zoneSafe:true,baseLong:3,baseShort:3,zoneFreeLong:1,zoneFreeShort:1,
    entryPriority:"LONG",availableText:"US$ 4,00",
    activeZoneEntryUsd:250,entrySizingMode:"notional",minimumLeverage:50,
    entryBudget:{availableUsd:4,requiredInitialMarginUsd:5,safetyBufferUsd:.25,requiredTotalUsd:5.25,shortfallUsd:1.25,status:"INSUFFICIENT"},
  });
  assert.equal(vm.estimatedSoldierCost,5);
  assert.equal(vm.nextPossibleInflow,"GEEN");
  assert.match(vm.nextPossibleDetail,/Available/i);
  assert.match(vm.nextPossibleDetail,/1,25/);
  assert.equal(vm.entryBudget.requiredTotalUsd,5.25);
});

test("missing canonical runtime budget fails closed instead of estimating an entry in the UI",()=>{
  const vm=buildStrategyStatusCommandCenter({
    strategyEnabled:true,zoneSafe:true,baseLong:3,baseShort:3,
    zoneOpenLong:2,zoneOpenShort:2,zoneFreeLong:1,zoneFreeShort:1,
    entryPriority:"LONG",availableText:"US$ 100,00",
    activeZoneEntryUsd:250,entrySizingMode:"notional",minimumLeverage:50,
  });
  assert.equal(vm.nextPossibleInflow,"GEEN");
  assert.match(vm.nextPossibleDetail,/runtime budgetcheck/i);
});

test("Build 430 exposes account scope and reconciliation without confusing zone formation with account totals",()=>{
  const vm=buildStrategyStatusCommandCenter({
    strategyEnabled:true,zoneSafe:true,baseLong:3,baseShort:3,
    zoneOpenLong:3,zoneOpenShort:3,zoneFreeLong:0,zoneFreeShort:0,
    actualLong:66,actualShort:43,
    reconciliation:{
      status:"SYNCED",liveDataStatus:"LIVE",snapshotId:"abc123",snapshotAgeMs:700,
      exchangePositions:109,exchangeLong:66,exchangeShort:43,soldiersTotal:30,nonSoldiersTotal:79,
      classifiedPositions:109,unclassifiedPositions:0,
      categories:{soldiersCurrentZone:6,soldiersOldZones:24,legacyAster:79,unknown:0},
      longExposureUsd:1037,shortExposureUsd:1759,netExposureUsd:-722,netExposureSide:"SHORT",
      hedgeCoveragePercent:169.624,
      margin:{availableUsd:26.5},
    },
  });
  assert.equal(vm.totalZoneSeats,6);
  assert.equal(vm.accountTotal,109);
  assert.equal(vm.accountLong,66);
  assert.equal(vm.accountShort,43);
  assert.equal(vm.soldiersTotal,30);
  assert.equal(vm.nonSoldiersTotal,79);
  assert.equal(vm.soldierCurrentZone,6);
  assert.equal(vm.soldierOldZones,24);
  assert.equal(vm.netExposureUsd,-722);
  assert.equal(vm.reconciliationStatus,"SYNCED");
  assert.equal(vm.liveDataStatus,"LIVE");
});

test("old-zone open soldiers and winning homecomings are separate truths",()=>{
  const now=Date.parse("2026-09-24T20:30:00Z");
  const vm=buildStrategyStatusCommandCenter({
    strategyEnabled:true,zoneSafe:true,activeZone:-1,baseLong:3,baseShort:3,
    zoneOpenLong:2,zoneOpenShort:1,zoneFreeLong:1,zoneFreeShort:2,
    oldZonesOpenLong:4,oldZonesOpenShort:3,
    homecomingEvents:[
      {eventId:"a",closedAtMs:Date.parse("2026-09-24T08:00:00Z"),reason:"TP_WIN_OUTSIDE_ORIGIN_ZONE",originZone:0,currentZoneAtClose:-1},
      {eventId:"b",closedAtMs:Date.parse("2026-09-24T19:00:00Z"),reason:"TP_WIN_OUTSIDE_ORIGIN_ZONE",originZone:1,currentZoneAtClose:-1},
      {eventId:"same",closedAtMs:Date.parse("2026-09-24T19:30:00Z"),reason:"TP_WIN_OUTSIDE_ORIGIN_ZONE",originZone:-1,currentZoneAtClose:-1},
      {eventId:"legacy",closedAtMs:Date.parse("2026-09-24T20:00:00Z"),reason:"TP_WIN",originZone:0},
      {eventId:"old",closedAtMs:Date.parse("2026-09-23T08:00:00Z"),reason:"TP_WIN_OUTSIDE_ORIGIN_ZONE",originZone:0,currentZoneAtClose:-1},
    ],
    nowMs:now,
  });
  assert.equal(vm.oldZonesOpenTotal,7);
  assert.equal(vm.winningHomeToday,2);
  assert.equal(vm.winningHomeTotal,3);
  assert.equal(vm.footerTitle,"Alleen oude-zone soldaten tellen als thuiskomst");
});

test("homecoming count accepts only proven outside-origin wins and deduplicates",()=>{
  const now=Date.parse("2026-09-24T12:00:00Z");
  const at=Date.parse("2026-09-24T10:00:00Z");
  assert.equal(countWinningHomecomingsToday([
    {eventId:"one",closedAtMs:at,reason:"TP_WIN_OUTSIDE_ORIGIN_ZONE",originZone:0,currentZoneAtClose:-1},
    {eventId:"one",closedAtMs:at,reason:"TP_WIN_OUTSIDE_ORIGIN_ZONE",originZone:0,currentZoneAtClose:-1},
    {eventId:"same",closedAtMs:at,reason:"TP_WIN_OUTSIDE_ORIGIN_ZONE",originZone:-1,currentZoneAtClose:-1},
    {eventId:"legacy",closedAtMs:at,reason:"TP_WIN",originZone:0},
    {eventId:"loss",closedAtMs:at,reason:"STOP_LOSS",originZone:0,currentZoneAtClose:-1},
  ],now),1);
});

test("soldier opening activity diagnostics remain available",()=>{
  const events=soldierOpenEventsFromManagedPositions({
    "BTCUSDT|LONG":{cycleStartedAtMs:1_000_000,soldierId:"s1",soldierRole:"ZONE_BASE",originZone:-1},
    "ETHUSDT|SHORT":{cycleStartedAtMs:1_010_000,soldierId:"s2",soldierRole:"EXPOSURE_BALANCER",originZone:-1},
  });
  assert.equal(events.length,2);
  const now=1_020_000;
  const summary=summarizeSoldierActivity(events,now);
  assert.ok(summary.windows["15m"].total>=2);
  assert.equal(mergeSoldierActivityHistory(events,[],now+60_000).length,2);
});
