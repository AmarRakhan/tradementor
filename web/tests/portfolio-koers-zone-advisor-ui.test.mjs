import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Build 405 keeps the approved zone-advisor reference owner-BETA gated",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes('ZONE_ADVISOR_REFERENCE="file_00000000d9b081f59f77ecf35043ec32"'));
  assert.ok(component.includes('authenticatedRequest("/api/releases/me"'));
  assert.ok(component.includes('String(release.channel||"").toUpperCase()==="BETA"&&betaFeature.enabled===true'));
  assert.ok(component.includes('className={advisorEnabled?"portfolio-koers-card beta-zone-advisor":"portfolio-koers-card"}'));
});

test("soldier action persists only seat capacity and never sends a direct exchange order",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes('authenticatedRequest("/api/exchanges/aster/strategy2/settings",{method:"PUT"'));
  assert.ok(component.includes("longSlots:targetLong"));
  assert.ok(component.includes("shortSlots:targetShort"));
  assert.ok(component.includes("maximumPositions:targetLong+targetShort"));
  assert.ok(component.includes("targetLong+targetShort>100"));
  assert.equal(component.includes("/order"),false);
  assert.equal(component.includes("manual-close"),false);
  assert.equal(component.includes("close-all"),false);
});

test("zone labels stay hidden while BETA zone contrast is visibly stronger",async()=>{
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(css.includes(".beta-zone-advisor .portfolio-koers-zone.zone-red"));
  assert.ok(css.includes(".beta-zone-advisor .portfolio-koers-zone.zone-amber"));
  assert.ok(css.includes(".beta-zone-advisor .portfolio-koers-zone.zone-green"));
  assert.ok(css.includes(".beta-zone-advisor .portfolio-koers-zone.zone-blue"));
  assert.ok(css.includes(".beta-zone-advisor .portfolio-koers-zone span{display:none!important}"));
  assert.ok(css.includes(".portfolio-koers-instruction"));
});

test("reference instruction text exposes desired and current formation with one functional button",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("KOERSINSTRUCTIE · ZONE"));
  assert.ok(component.includes("Stuur ${instructionAmount} extra ${instructionSide}-soldaten"));
  assert.ok(component.includes("Roep ${instructionAmount} ${instructionSide}-soldaten naar huis"));
  assert.ok(component.includes("Gewenst:"));
  assert.ok(component.includes("Huidig:"));
  assert.ok(component.includes("applySoldierInstruction()"));
});
