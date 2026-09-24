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
  assert.ok(component.includes("targetLong+targetShort>PORTFOLIO_ZONE_MAX_TOTAL_SLOTS"));
  assert.ok(component.includes("MAX ${PORTFOLIO_ZONE_MAX_TOTAL_SLOTS}"));
  assert.equal(component.includes("LIMIET 100"),false);
  assert.ok(component.includes("Serververbinding onderbroken · er is niets gewijzigd. Probeer opnieuw."));
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

test("formation dashboard distinguishes active soldiers, capacity, free seats and zone target with one functional button",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("KOERSINSTRUCTIE · Z{signedZone(activeZone)} · {biasLabel}"));
  assert.ok(component.includes("SOLDATEN ACTIEF"));
  assert.ok(component.includes("CAPACITEIT"));
  assert.ok(component.includes("VRIJ"));
  assert.ok(component.includes("DOEL"));
  assert.ok(component.includes("activeTotal"));
  assert.ok(component.includes("freeLong"));
  assert.ok(component.includes("freeShort"));
  assert.ok(component.includes("desiredLong"));
  assert.ok(component.includes("desiredShort"));
  assert.ok(component.includes("applySoldierInstruction()"));
});


test("Build 406/408 uses the extrapolated ladder context for BETA active zone instead of nearest confirmed center",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("derivePortfolioZoneLadder(advisorZoneSource)"));
  assert.ok(component.includes("portfolioZoneContextFromLadder(advisorZoneLadder,currentZonePrice)"));
  assert.ok(component.includes("advisorEnabled?zoneContext?.activeIndex??null:confirmedActiveZone"));
});

test("BETA ladder fills the complete chart height including the outer zones",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("zone.upper===Infinity?0"));
  assert.ok(component.includes("zone.lower===-Infinity?height"));
  assert.ok(component.includes("Math.max(0,bottom-top)"));
});

test("BETA semantic zone colors are no longer swapped",async()=>{
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(css.includes(".beta-zone-advisor .portfolio-koers-zone.zone-green{border-color:rgba(28,224,154"));
  assert.ok(css.includes(".beta-zone-advisor .portfolio-koers-zone.zone-blue{border-color:rgba(45,157,232"));
});


test("Build 407 uses one canonical 15m zone source for every BETA chart timeframe",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes('/api/exchanges/aster/portfolio-chart?timeframe=15m&limit=320'));
  assert.ok(component.includes("setAdvisorZones(canonical.zones)"));
  assert.ok(component.includes("advisorEnabled&&advisorZones.length?advisorZones:payload.zones"));
  assert.ok(component.includes("derivePortfolioZoneLadder(advisorZoneSource)"));
});

test("canonical 15m zone fetch is BETA-only and fails closed when continuity evidence is unavailable",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const betaGate=component.indexOf('if(!enabled){setAdvisorSeats(EMPTY_ADVISOR);setAdvisorZones([])');
  const canonicalFetch=component.indexOf('/portfolio-chart?timeframe=15m&limit=320');
  assert.ok(betaGate>0);
  assert.ok(canonicalFetch>betaGate);
  assert.ok(component.includes("catch{\n        setAdvisorZones([]);\n        setAdvisorTimeline(null);\n      }"));
  assert.ok(component.includes('const instructionActionable=advisorTimelineReady&&["ADD","PARTIAL_ADD","REMOVE"].includes(instructionStatus)'));
  assert.ok(component.includes('!advisorTimelineReady?"WACHTEN"'));
});


test("Build 408 renders unique structural boundaries instead of borders on every zone block",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(component.includes("portfolio-koers-zone-boundaries"));
  assert.ok(component.includes("portfolio-koers-zone-boundary"));
  assert.ok(component.includes('"next-up"'));
  assert.ok(component.includes('"next-down"'));
  assert.ok(css.includes(".beta-zone-advisor .portfolio-koers-zone{border:0"));
  assert.ok(css.includes(".portfolio-koers-zone-boundary.next-up"));
  assert.ok(css.includes(".portfolio-koers-zone-boundary.next-down"));
});

test("Build 408 gives adjacent signed zones visibly different fills and a stronger active zone",async()=>{
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  for(const level of ["level-n3","level-n2","level-n1","level-0","level-p1","level-p2","level-p3"]){
    assert.ok(css.includes(".beta-zone-advisor .portfolio-koers-zone."+level));
  }
  assert.ok(css.includes(".beta-zone-advisor .portfolio-koers-zone.active"));
  assert.ok(css.includes("brightness(1.14)"));
});

test("Build 408 explains no-action state and shows exact next upper and lower triggers",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("instructionReason"));
  assert.ok(component.includes("portfolio-koers-instruction-reason"));
  assert.equal(component.includes("VOLGENDE LEVEL"),false);
  assert.ok(component.includes("portfolioZoneDistancePercent"));
  assert.ok(component.includes("upperTrigger"));
  assert.ok(component.includes("lowerTrigger"));
  assert.ok(component.includes("nextUpIndex"));
  assert.ok(component.includes("nextDownIndex"));
});

test("Build 408 bias badge summarizes active zone and desired formation without loose chart zone labels",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(component.includes("Z{signedZone(activeZone)}"));
  assert.ok(component.includes("zoneLevelClass(zone.index)"));
  assert.ok(component.includes("<span>{zone.label}</span>"));
  assert.ok(css.includes(".beta-zone-advisor .portfolio-koers-zone span{display:none!important}"));
});

test("Build 408 re-confirms canonical zone before a functional soldier write",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const actionStart=component.indexOf("const applySoldierInstruction");
  const actionSource=component.slice(actionStart,component.indexOf("const latest=",actionStart));
  assert.ok(actionSource.includes("/portfolio-chart?timeframe=15m&limit=320"));
  assert.ok(actionSource.includes("derivePortfolioZoneLadder(canonical.zones)"));
  assert.ok(actionSource.includes("portfolioZoneFromLadder(freshLadder,freshPrice)"));
  assert.ok(actionSource.includes("if(freshZone===null)"));
});

test("Build 408 makes ordinary chart grid quieter only for the BETA decision map",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes('advisorEnabled?"rgba(75,133,160,.025)"'));
  assert.ok(component.includes('advisorEnabled?"rgba(75,133,160,.032)"'));
});


test("Build 409 makes the three lower zones visibly different instead of one green mass",async()=>{
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(css.includes("level-n3{background:linear-gradient(90deg,rgba(2,45,38,.76)"));
  assert.ok(css.includes("level-n2{background:linear-gradient(90deg,rgba(3,82,76,.68)"));
  assert.ok(css.includes("level-n1{background:linear-gradient(90deg,rgba(5,111,66,.62)"));
  assert.ok(css.includes("level-0{background:linear-gradient(90deg,rgba(6,59,120,.68)"));
});

test("Build 409 keeps ordinary structural boundaries neutral so lower levels cannot look like random green lines",async()=>{
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(css.includes(".portfolio-koers-zone-boundary.regular{border-top-color:rgba(205,218,222,.13);opacity:.72}"));
  assert.ok(css.includes(".portfolio-koers-zone-boundary.next-up{border-top:2px solid rgba(242,195,64,.92)"));
  assert.ok(css.includes(".portfolio-koers-zone-boundary.next-down{border-top:2px solid rgba(42,225,163,.82)"));
});

test("Build 409 keeps all seven signed zones separately styled",async()=>{
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  for(const level of ["level-n3","level-n2","level-n1","level-0","level-p1","level-p2","level-p3"]){
    const matches=css.match(new RegExp("\\."+level.replace("-","\\-")+"\\{background:","g"))||[];
    assert.ok(matches.length>=1,level+" must have its own fill");
  }
});


test("Build 410 explains exactly what determines the signed zone",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(component.includes("Zonebasis: portfolio-equity · 15m support/resistance"));
  assert.ok(component.includes("Netto exposure is geen verliesbedrag."));
  assert.ok(component.includes("zoneBandSummary"));
  assert.ok(component.includes("portfolio-koers-zone-basis"));
  assert.ok(css.includes(".portfolio-koers-instruction-copy>.portfolio-koers-zone-basis"));
});


test("Build 413 replaces ambiguous VOLGENDE price labels with directional zone percentages",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.equal(component.includes('"VOLGENDE ↑"'),false);
  assert.equal(component.includes('"VOLGENDE ↓"'),false);
  assert.ok(component.includes('boundary.kind==="next-up"?"↑":"↓"'));
  assert.ok(component.includes("percent2(distance)"));
  assert.ok(component.includes("↑ Nog ${percent2(upperDistancePercent)} tot Z"));
  assert.ok(component.includes("↓ ${percent2(lowerDistancePercent,false)} tot Z"));
  assert.ok(component.includes("portfolio-koers-zone-progress"));
  assert.ok(component.includes("Math.round(zoneProgressPercent)"));
});

test("Build 413 keeps exact absolute zone prices secondary in title text instead of the primary labels",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("Exacte grens ${levelUsd(boundary.price)}"));
  assert.ok(component.includes("Exacte zonegrenzen: ${zoneBandSummary}"));
});


test("Build 414 makes percentage zone badges more prominent than before without changing their live calculation",async()=>{
  const [component,css]=await Promise.all([
    readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8"),
    readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8"),
  ]);
  assert.ok(component.includes("portfolioZoneDistancePercent(boundary.price,currentZonePrice)"));
  assert.ok(css.includes(".portfolio-koers-zone-boundary>span{min-width:82px;padding:3px 6px;font-size:8.2px"));
  assert.ok(css.includes("font-size:7.6px"));
});

test("Build 414 keeps the instruction button as seat-capacity persistence only",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("longSlots:targetLong"));
  assert.ok(component.includes("shortSlots:targetShort"));
  assert.ok(component.includes("maximumPositions:targetLong+targetShort"));
  assert.equal(component.includes("/order"),false);
});
