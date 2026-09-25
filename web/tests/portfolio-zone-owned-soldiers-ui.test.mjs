import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { buildStrategyStatusCommandCenter } from "../lib/strategy-status-command-center.mjs";

test("Build 432 command center prioritises live strategy-owned state over free configuration seats",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("ZONE-SOLDATEN ACTIEF"));
  assert.ok(component.includes("OUDE-ZONE POSITIES"));
  assert.ok(component.includes("VOLGENDE ZONES"));
  assert.ok(component.includes("ACTIEVE ZONE"));
  assert.ok(component.includes("NETTO EXPOSURE"));
  assert.equal(component.includes("THUIS / BESCHIKBAAR"),false);
  assert.equal(component.includes("VOLGENDE MOGELIJKE INSTROOM"),false);
  assert.equal(component.includes("<small>ENTRY-PRIORITEIT</small>"),false);
  assert.equal(component.includes("portfolio-koers-bias"),false);
});

test("Build 432 keeps zone status strictly read-only and never writes seats or orders",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.equal(component.includes("applySoldierInstruction"),false);
  assert.equal(component.includes("derivePortfolioZoneInstruction"),false);
  assert.equal(component.includes('method:"PUT"'),false);
  assert.equal(component.includes('method:"POST"'),false);
  assert.ok(component.includes('zoneSoldierLifecycle==="DRAINING"'));
});

test("Build 432 reconciles strategy-owned and old-zone soldier counts",()=>{
  const vm=buildStrategyStatusCommandCenter({
    strategyEnabled:true,
    zoneSafe:true,
    activeZone:2,
    baseLong:3,
    baseShort:3,
    zoneOpenLong:2,
    zoneOpenShort:1,
    zoneFreeLong:1,
    zoneFreeShort:2,
    strategyOwnedLong:14,
    strategyOwnedShort:16,
    strategyOwnedTotal:30,
    currentZoneOwnedLong:2,
    currentZoneOwnedShort:1,
    oldZonesOpenLong:12,
    oldZonesOpenShort:15,
    oldZonesOpenTotal:27,
    netExposureUsd:-638,
    netExposureSide:"SHORT",
    entryPriority:"LONG",
    nextZone:3,
    previousZone:1,
    nextZonePrice:350,
    previousZonePrice:300,
    currentEquity:341.51,
    availableText:"US$ 238,71",
  });
  assert.equal(vm.strategyOwnedLong,14);
  assert.equal(vm.strategyOwnedShort,16);
  assert.equal(vm.strategyOwnedTotal,30);
  assert.equal(vm.oldZonesOpenTotal,27);
  assert.equal(vm.oldZonesOpenLong+vm.oldZonesOpenShort,vm.oldZonesOpenTotal);
  assert.ok(vm.oldZonesOpenTotal<=vm.strategyOwnedTotal);
  assert.equal(vm.netExposureUsd,-638);
  assert.equal(vm.entryPriority,"LONG");
  assert.equal(vm.nextZoneUp,"Z+3");
  assert.equal(vm.nextZoneDown,"Z+1");
  assert.ok(vm.nextZoneUpDistancePercent>0);
  assert.ok(vm.nextZoneDownDistancePercent>0);
});

test("Build 432 does not falsely call unknown sizing an insufficient-Available condition",()=>{
  const vm=buildStrategyStatusCommandCenter({
    strategyEnabled:true,
    zoneSafe:true,
    activeZone:2,
    baseLong:3,
    baseShort:3,
    zoneFreeLong:3,
    zoneFreeShort:1,
    availableText:"US$ 238,71",
    entryPriority:"LONG",
  });
  assert.equal(vm.availabilityStatus,"UNKNOWN");
  assert.equal(vm.nextPossibleDetail,"Available-check onbekend · geen kostenbedrag afgeleid");
  assert.notEqual(vm.nextPossibleDetail,"wacht op voldoende Available");
});

test("Build 432 marks Available enough or not enough only when soldier cost is known",()=>{
  const base={
    strategyEnabled:true,zoneSafe:true,activeZone:2,baseLong:3,baseShort:3,
    zoneFreeLong:1,zoneFreeShort:1,entryPriority:"LONG",activeZoneEntryUsd:100,
    entrySizingMode:"margin",minimumLeverage:20,entryFeeBufferUsd:1,minimumOrderMarginUsd:0,
  };
  const enough=buildStrategyStatusCommandCenter({...base,availableText:"US$ 238,71"});
  assert.equal(enough.estimatedSoldierCost,101);
  assert.equal(enough.requiredAvailable,106.05000000000001);
  assert.equal(enough.availabilityStatus,"ENOUGH");
  const low=buildStrategyStatusCommandCenter({...base,availableText:"US$ 50,00"});
  assert.equal(low.availabilityStatus,"NOT_ENOUGH");
  assert.equal(low.nextPossibleDetail,"wacht op voldoende Available");
});

test("Build 432 mobile CSS uses two-column minmax grids and protects dynamic values from overflow",async()=>{
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(css.includes(".pcc-status-grid-v2{grid-template-columns:repeat(2,minmax(0,1fr))!important}"));
  assert.ok(css.includes("overflow-wrap:anywhere"));
  assert.ok(css.includes("@media(max-width:380px)"));
});
