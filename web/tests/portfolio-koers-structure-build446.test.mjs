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
  assert.ok(component.includes("const rawLevels=[...resistanceLevels,...supportLevels]"));
  assert.ok(component.includes('label:"R1"'));
  assert.ok(component.includes('label:"S1"'));
  assert.ok(component.includes('label:`R${offset+1}`'));
  assert.ok(component.includes('label:`S${offset+1}`'));
});

test("Build 551 supersedes the Build 513 cleanup and restores the in-chart active-zone block",async()=>{
  const [component,css]=await Promise.all([
    readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8"),
    readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8"),
  ]);
  assert.ok(component.includes("activeZone:activeTop!==null&&activeBottom!==null"));
  assert.ok(css.includes(".portfolio-koers-ui41 .portfolio-koers-structure-zone{"));
  assert.doesNotMatch(css,/\.portfolio-koers-ui41 \.portfolio-koers-structure-zone\{\s*display:none!important/);
  assert.equal(component.includes("voormalige R1 → nieuwe support"),false);
});

test("Build 509 binds the active gold zone to the same operational zone used by the footer",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("const operationalIndex=activeZoneRef.current"));
  assert.ok(component.includes("const activeLower=Number.isFinite(Number(activeRow?.lower))"));
  assert.ok(component.includes("const activeUpper=Number.isFinite(Number(activeRow?.upper))"));
  assert.ok(component.includes('candles[index-1].close<=Number(activeLower)&&candles[index].close>Number(activeLower)'));
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

test("Build 479 is the advertised webapp build while Build 447 Graph 3.1 regressions remain protected",async()=>{
  const version=await readFile(new URL("../lib/app-version.ts",import.meta.url),"utf8");
  assert.match(version,/WEBAPP_BUILD_NUMBER = "490"/);
});


test("Build 551 restores the reference R1-R4 and S1-S4 display cap",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("extendPortfolioZoneLadderToPrice(base,currentZonePrice,4)"));
  assert.ok(component.includes("portfolioZoneContextFromLadder(zoneLadder,structurePrice)"));
  assert.ok(component.includes("const resistanceLevels=Array.from({length:4}"));
  assert.ok(component.includes("const supportLevels=Array.from({length:4}"));
  assert.ok(component.includes("if(top<0||top>height)return []"));
});

test("Build 513 disables legacy breakout structure notes",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("breakout:null"));
  assert.ok(component.includes("setStructureOverlay({...structureDraft,roleFlip:null,newHigh:null,breakout:null})"));
});

test("Build 474 keeps marker collision layout after reference-density selection and hides legacy structure notes",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("selectPortfolioKoersReferenceCandidates(candidates"));
  assert.ok(component.includes("layoutPortfolioKoersMarkers(displayCandidates"));
  assert.ok(component.includes("markerLayout.all"));
  assert.ok(component.includes("setStructureOverlay({...structureDraft,roleFlip:null,newHigh:null,breakout:null})"));
  assert.equal(component.includes("placeStructureNote(structureDraft.newHigh"),false);
});


test("Portfolio Snapshot exposes the exact read-only entry blocker beside free zone seats", async () => {
  const component = await readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8");
  assert.ok(component.includes("entryDiagnostics"));
  assert.ok(component.includes("dynamicHedgeBlocking"));
  assert.ok(component.includes("Instap geblokkeerd · Dynamic Hedge"));
  assert.ok(component.includes("Instapstatus ·"));
  assert.ok(component.includes("orderreconciliatie"));
});