import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Build 421 gates the new Command Center on hard betaOwner only",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("const { user, betaOwner }=useAuthSession()"));
  assert.ok(component.includes("const commandCenterTester=betaOwner===true"));
  assert.ok(component.includes("commandCenterTester&&"));
  assert.ok(component.includes("!commandCenterTester&&"));
  assert.equal(component.includes('commandCenterTester=String(release.channel'),false);
});

test("non-owner accounts keep the existing Strategy Cockpit markup",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes('!commandCenterTester&&(activeZone!==null||zoneSoldierEnabled||zoneSoldierLifecycle==="DRAINING")'));
  assert.ok(component.includes("portfolio-strategy-cockpit"));
  assert.ok(component.includes("Strategiestatus"));
});

test("owner Command Center uses the requested reference and same Snapshot truth props",async()=>{
  const [component,enhancer]=await Promise.all([
    readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8"),
    readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx",import.meta.url),"utf8"),
  ]);
  assert.ok(component.includes('data-reference="file_00000000d9b0820e8eacdecb418c95aa"'));
  assert.ok(enhancer.includes("liveAvailableText={values.available}"));
  assert.ok(enhancer.includes("liveLongText={values.longs}"));
  assert.ok(enhancer.includes("liveShortText={values.shorts}"));
  assert.ok(component.includes("actualLong:liveLongText"));
  assert.ok(component.includes("actualShort:liveShortText"));
  assert.ok(component.includes("availableText:liveAvailableText"));
});

test("Command Center has no manual buy or mutation path",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const start=component.indexOf("function StrategyCommandCenter");
  const end=component.indexOf("export function PortfolioKoersChart",start);
  const block=component.slice(start,end);
  assert.ok(block.includes("BOT KOOPT AUTOMATISCH"));
  assert.equal(block.includes('method:"PUT"'),false);
  assert.equal(block.includes('method:"POST"'),false);
  assert.equal(block.includes("onClick"),false);
  assert.equal(block.includes("Koop 4"),false);
});

test("Command Center renders all requested status dimensions",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  for(const label of [
    "NU ACTIE","ACTIEVE ZONE","VOLGENDE ZONE","VORIGE ZONE","FORMATIE PER ZONE",
    "ACTIEVE SOLDATEN","BALANS LONG / SHORT","RESERVE / AVAILABLE",
    "GESCHATTE EXTRA SOLDATEN","DCA-RUNWAY","ZONE-VOORRAAD","HOE LANG HOUDEN WE DIT VOL?"
  ]) assert.ok(component.includes(label),label);
});

test("Build 421 responsive Command Center covers 360 390 and 430 class of mobile widths without horizontal overflow",async()=>{
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(css.includes(".pcc-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))"));
  assert.ok(css.includes("@media(max-width:560px)"));
  assert.ok(css.includes("@media(max-width:380px)"));
  assert.ok(css.includes("minmax(0,1fr)"));
  assert.equal(css.includes("overflow-x:scroll"),false);
});


test("Build 422 owner Command Center shows soldier activity windows and recent confirmed openings",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  for(const label of ["SOLDATENACTIVITEIT","15m","1u","4u","24u","LAATSTE TOEVOEGINGEN","BEVESTIGDE OPENINGEN"]){
    assert.ok(component.includes(label),label);
  }
  assert.ok(component.includes("vm.soldierActivity.windows[key]"));
  assert.ok(component.includes("vm.soldierActivity.recent"));
});

test("Build 422 activity reuses the existing advisor polling loop instead of adding an aggressive timer",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("nextAdvisor.soldierOpenEvents"));
  assert.ok(component.includes("mergeSoldierActivityHistory(current,nextAdvisor.soldierOpenEvents,Date.now())"));
  const timers=[...component.matchAll(/setInterval\([^,]+,\s*([0-9_]+)/g)].map((match)=>Number(match[1].replaceAll("_","")));
  assert.ok(timers.every((value)=>value>=45_000));
});

test("Build 422 activity remains inside the betaOwner-only Command Center path",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("const commandCenterTester=betaOwner===true"));
  assert.ok(component.includes("if(!commandCenterTester||!user?.uid){setSoldierActivity([]);return}"));
  assert.ok(component.includes("commandCenterTester&&(activeZone!==null||zoneSoldierEnabled||zoneSoldierLifecycle===\"DRAINING\")?<StrategyCommandCenter"));
});
