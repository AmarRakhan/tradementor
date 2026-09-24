import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("new Command Center remains hard betaOwner-only while non-owner keeps existing cockpit",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("const { user, betaOwner }=useAuthSession()"));
  assert.ok(component.includes("const commandCenterTester=betaOwner===true"));
  assert.ok(component.includes("commandCenterTester&&"));
  assert.ok(component.includes("!commandCenterTester&&"));
  assert.ok(component.includes("portfolio-strategy-cockpit"));
});

test("owner Command Center uses approved homecoming visual reference",async()=>{
  const [component,viewModel]=await Promise.all([
    readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8"),
    readFile(new URL("../lib/strategy-status-command-center.mjs",import.meta.url),"utf8"),
  ]);
  assert.ok(component.includes('data-reference="file_000000009e0081f4b88f4b415de68c71"'));
  for(const label of [
    "ACTIEVE FORMATIE","NETTO EXPOSURE:","THUIS / BESCHIKBAAR","IN HET VELD",
    "OUDE ZONES NOG BUITEN","WINST THUISGEKOMEN","ENTRY-PRIORITEIT","VOLGENDE MOGELIJKE INSTROOM",
  ]) assert.ok(component.includes(label),label);
  assert.ok(viewModel.includes('footerTitle:"Alleen oude-zone soldaten tellen als thuiskomst"'));
  assert.ok(viewModel.includes('footerDetail:"Winst in de eigen actieve zone maakt dezelfde soldaat opnieuw beschikbaar"'));
  assert.ok(component.includes("oude-zone soldaten terug met winst"));
});

test("owner Command Center removes bulk-soldier messaging and mutation controls",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const start=component.indexOf("function StrategyCommandCenter");
  const end=component.indexOf("export function PortfolioKoersChart",start);
  const block=component.slice(start,end);
  assert.equal(block.includes("BOT KOOPT AUTOMATISCH"),false);
  assert.equal(block.includes("GESCHATTE EXTRA SOLDATEN"),false);
  assert.equal(block.includes("NU ACTIE"),false);
  assert.equal(block.includes('method:"PUT"'),false);
  assert.equal(block.includes('method:"POST"'),false);
  assert.equal(block.includes("onClick"),false);
});

test("Command Center receives active-zone occupancy old zones exposure priority and TP homecomings",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  for(const token of [
    "zoneOpenLong","zoneOpenShort","oldZonesOpenTotal:oldOpenTotal",
    "netExposureSide","entryPriority:zoneSoldierReport.entryPriority",
    "homecomingEvents:Array.isArray(zoneHomecomings.events)",
  ]) assert.ok(component.includes(token),token);
});

test("fixed-formation mobile grid matches approved three-by-two reference",async()=>{
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(css.includes("file_000000009e0081f4b88f4b415de68c71"));
  assert.ok(css.includes(".pcc-status-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))"));
  assert.ok(css.includes("@media(max-width:560px)"));
  assert.ok(css.includes("@media(max-width:380px)"));
});

test("existing advisor refresh remains no faster than 45 seconds",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const timers=[...component.matchAll(/setInterval\([^,]+,\s*([0-9_]+)/g)].map((match)=>Number(match[1].replaceAll("_","")));
  assert.ok(timers.every((value)=>value>=45_000));
});
