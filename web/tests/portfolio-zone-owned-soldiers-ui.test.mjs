import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Build 415 Formation Dashboard reads persistent zone-owned runtime state",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("zoneSoldiers"));
  assert.ok(component.includes("zoneSoldierEnabled"));
  assert.ok(component.includes("signedIntegerOrNull(zoneSoldierReport.activeZone)"));
  assert.ok(component.includes("ZONE-OWNED"));
  assert.ok(component.includes("ZONEFORMATIE"));
  assert.ok(component.includes("IN ZONE OPEN"));
  assert.ok(component.includes("IN ZONE VRIJ"));
  assert.ok(component.includes("Oude zones nog open"));
  assert.ok(component.includes("legacyUnassignedOpen"));
  assert.ok(component.includes("Exposure:"));
});

test("Build 415 disables the old global seat write while zone-owned automation is active",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes('const actionLabel=zoneSoldierEnabled?(zoneEntriesSafe?"AUTO":"WACHTEN")'));
  assert.ok(component.includes("disabled={zoneSoldierEnabled||!instructionActionable||advisorBusy}"));
  assert.ok(component.includes("if(!zoneSoldierEnabled)void applySoldierInstruction()"));
  assert.ok(component.includes("advisorEnabled&&!zoneSoldierEnabled?derivePortfolioZoneInstruction"));
});

test("Build 415 keeps percentage zone navigation and compact zone-owned styles",async()=>{
  const [component,css]=await Promise.all([
    readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8"),
    readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8"),
  ]);
  assert.ok(component.includes("portfolioZoneDistancePercent"));
  assert.ok(component.includes("portfolio-koers-zone-progress"));
  assert.ok(css.includes("Build 415 · zone-owned soldier formation dashboard"));
  assert.ok(css.includes(".portfolio-koers-old-zones"));
  assert.ok(css.includes(".portfolio-koers-exposure-line"));
});
