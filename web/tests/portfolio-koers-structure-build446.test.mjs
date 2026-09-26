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

test("Build 446 is the advertised webapp build",async()=>{
  const version=await readFile(new URL("../lib/app-version.ts",import.meta.url),"utf8");
  assert.match(version,/WEBAPP_BUILD_NUMBER = "446"/);
});
