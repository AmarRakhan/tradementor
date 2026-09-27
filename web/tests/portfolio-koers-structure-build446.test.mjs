import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const REFERENCE="file_00000000035481f4bb41632c35857982";
const BASELINE="file_000000002c048243bcc70e9957bb001e";

test("Build 446 binds Portfolio Koers Graph 3.0 to the approved structure reference",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes(`PORTFOLIO_STRUCTURE_REFERENCE="${REFERENCE}"`));
  assert.ok(component.includes(`PORTFOLIO_STRUCTURE_BASELINE_REFERENCE="${BASELINE}"`));
  assert.ok(component.includes("portfolio-koers-structure-layer"));
  for(const label of ['label:"R2"','label:"R1"','label:"S1"','label:"S2"'])assert.ok(component.includes(label),label);
});

test("Build 446 renders one active gold zone and the three requested market-structure annotations",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("portfolio-koers-structure-zone"));
  assert.ok(component.includes("Zone ${Number(activeIndex)} actief"));
  assert.ok(component.includes("voormalige R1 → nieuwe support"));
  assert.ok(component.includes("nieuwe high"));
  assert.ok(component.includes("volgende breakout"));
});

test("Build 446 defines the active zone by S1/R1 so a broken resistance can become the next support",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("marketContext?.lowerBoundary"));
  assert.ok(component.includes("marketContext?.upperBoundary"));
  assert.ok(component.includes("const activeLower=s1"));
  assert.ok(component.includes("const activeUpper=r1"));
  assert.ok(component.includes('candles[index-1].close<=Number(s1)&&candles[index].close>Number(s1)'));
});

test("Build 446 keeps the right price axis calm and does not add volume or a side summary",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("priceLineVisible:false,lastValueVisible:false"));
  assert.ok(component.includes('axisLabelVisible:false,title:""'));
  assert.equal(component.includes("portfolio-koers-volume"),false);
  assert.equal(component.includes("portfolio-koers-structure-summary"),false);
});

test("Build 446 visual layer overrides legacy multicolor zone fills without deleting compatibility code",async()=>{
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(css.includes("Build 446 · Portfolio Koers Graph 3.0"));
  assert.ok(css.includes(".portfolio-zone-map .portfolio-koers-zones .portfolio-koers-zone"));
  assert.ok(css.includes("background:transparent!important"));
  assert.ok(css.includes(".portfolio-zone-map .portfolio-koers-zone-boundaries{display:none!important}"));
  assert.ok(css.includes(".portfolio-koers-structure-level.resistance{color:#ff5967}"));
  assert.ok(css.includes(".portfolio-koers-structure-level.support{color:#19dda0}"));
  assert.ok(css.includes("border-top:1.5px dashed currentColor"));
});

test("Build 446 remains read-only and does not introduce trading mutation paths",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.equal(component.includes('method:"PUT"'),false);
  assert.equal(component.includes('method:"POST"'),false);
  assert.equal(component.includes("/order"),false);
  assert.equal(component.includes("applySoldierInstruction"),false);
});

test("Build 455 is the advertised webapp build while Build 447 Graph 3.1 regressions remain protected",async()=>{
  const version=await readFile(new URL("../lib/app-version.ts",import.meta.url),"utf8");
  assert.match(version,/WEBAPP_BUILD_NUMBER = "455"/);
});


test("Build 447 derives visible active zone from the current live price instead of capped +3",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("extendPortfolioZoneLadderToPrice(base,currentZonePrice,2)"));
  assert.ok(component.includes("portfolioZoneContextFromLadder(zoneLadder,structurePrice)"));
  assert.ok(component.includes("const activeLower=s1"));
  assert.ok(component.includes("const activeUpper=r1"));
});

test("Build 447 puts the next breakout at R1, the first resistance above the active zone",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("breakout:r1Level?"));
  assert.equal(component.includes("breakout:(r2Level??r1Level)"),false);
});

test("Build 447 structure notes are collision-aware against trade markers",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("placeStructureNote(structureDraft.newHigh"));
  assert.ok(component.includes("markerLayout.all,reserved"));
  assert.ok(component.includes("structureRectsOverlap"));
  assert.ok(component.includes('kind==="newHigh"'));
});
