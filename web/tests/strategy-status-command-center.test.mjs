import assert from "node:assert/strict";
import test from "node:test";
import { buildStrategyStatusCommandCenter, parsePortfolioMoney } from "../lib/strategy-status-command-center.mjs";

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
