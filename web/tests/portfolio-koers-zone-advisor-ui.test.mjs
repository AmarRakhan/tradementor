import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";


test("Build 417 keeps zone-trading availability owner-BETA gated while zones stay informational",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes('ZONE_ADVISOR_REFERENCE="file_00000000d9b081f59f77ecf35043ec32"'));
  assert.ok(component.includes('authenticatedRequest("/api/releases/me"'));
  assert.ok(component.includes("features.zone_soldiers"));
  assert.ok(component.includes('ownerStrategyAccess=String(release.channel||"").toUpperCase()==="BETA"&&zoneFeature.enabled===true'));
  assert.ok(component.includes("portfolio-zone-map"));
});


test("Build 417 Portfolio Koers is strictly read-only",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.equal(component.includes('authenticatedRequest("/api/exchanges/aster/strategy2/settings"'),false);
  assert.equal(component.includes("longSlots:targetLong"),false);
  assert.equal(component.includes("shortSlots:targetShort"),false);
  assert.equal(component.includes("maximumPositions:targetLong+targetShort"),false);
  assert.equal(component.includes("applySoldierInstruction"),false);
  assert.equal(component.includes('method:"PUT"'),false);
  assert.equal(component.includes("/order"),false);
  assert.ok(component.includes("INFORMATIEF"));
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


test("Build 420 strategy cockpit separates informative zones from explicit zone steering",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("ZONE-STURING ACTIEF"));
  assert.ok(component.includes("PORTFOLIOZONE"));
  assert.ok(component.includes("portfolio-strategy-cockpit"));
  assert.ok(component.includes("Strategiestatus"));
  assert.ok(component.includes("ACTIEVE ZONE"));
  assert.ok(component.includes("FORMATIE"));
  assert.ok(component.includes("ZONEFORMATIE"));
  assert.ok(component.includes("IN ZONE OPEN"));
  assert.ok(component.includes("IN ZONE VRIJ"));
  assert.equal(component.includes("applySoldierInstruction()"),false);
});


test("Build 417 uses the canonical ladder for informational active zone and zone strategy",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("derivePortfolioZoneLadder(advisorZoneSource)"));
  assert.ok(component.includes("portfolioZoneContextFromLadder(advisorZoneLadder,currentZonePrice)"));
  assert.ok(component.includes("zoneSoldierEnabled&&zoneSoldierActiveZone!==null?zoneSoldierActiveZone:zoneContext?.activeIndex??confirmedActiveZone"));
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



test("Build 417 uses one canonical 15m informational zone source for every chart timeframe",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes('/api/exchanges/aster/portfolio-chart?timeframe=15m&limit=320'));
  assert.ok(component.includes("setAdvisorZones(canonical.zones)"));
  assert.ok(component.includes("advisorTimeline?.safeForAdvisor===true&&advisorZones.length?advisorZones:payload.zones"));
  assert.ok(component.includes("derivePortfolioZoneLadder(advisorZoneSource)"));
});


test("Build 417 canonical 15m zones are informational for everyone and fail closed for trade steering",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes('/portfolio-chart?timeframe=15m&limit=320'));
  assert.ok(component.includes("setAdvisorZones(canonical.zones)"));
  assert.ok(component.includes("setAdvisorTimeline(portfolioKoersTimelineHealth"));
  assert.ok(component.includes("zoneEntriesSafe"));
  assert.ok(component.includes("informatief; geen orders of slotwijzigingen"));
  assert.ok(component.includes("Portfolio Koers blijft informatief"));
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


test("Build 417 informational state shows next upper and lower zone triggers without an action path",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.equal(component.includes("VOLGENDE LEVEL"),false);
  assert.ok(component.includes("portfolioZoneDistancePercent"));
  assert.ok(component.includes("upperTrigger"));
  assert.ok(component.includes("lowerTrigger"));
  assert.ok(component.includes("nextUpIndex"));
  assert.ok(component.includes("nextDownIndex"));
  assert.ok(component.includes("Geen automatische zone-acties"));
});

test("Build 408 bias badge summarizes active zone and desired formation without loose chart zone labels",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(component.includes("Z{signedZone(activeZone)}"));
  assert.ok(component.includes("zoneLevelClass(zone.index)"));
  assert.ok(component.includes("<span>{zone.label}</span>"));
  assert.ok(css.includes(".beta-zone-advisor .portfolio-koers-zone span{display:none!important}"));
});


test("Build 417 Portfolio Koers contains no functional soldier write path",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.equal(component.includes("const applySoldierInstruction"),false);
  assert.equal(component.includes("portfolioZoneFromLadder"),false);
  assert.equal(component.includes('method:"PUT"'),false);
  assert.ok(component.includes("derivePortfolioZoneLadder"));
});


test("Build 417 keeps one quiet chart grid for informational and zone-strategy modes",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes('vertLines:{color:"rgba(75,133,160,.035)"}'));
  assert.ok(component.includes('horzLines:{color:"rgba(75,133,160,.045)"}'));
  assert.equal(component.includes('advisorEnabled?"rgba(75,133,160'),false);
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



test("Build 420 keeps the signed zone basis available while the visible cockpit stays compact",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(component.includes("Zonebasis: portfolio-equity · 15m support/resistance"));
  assert.ok(component.includes("handelssturing expliciet actief"));
  assert.ok(component.includes("informatief; geen orders of slotwijzigingen"));
  assert.ok(component.includes("zoneBandSummary"));
  assert.ok(component.includes("portfolio-strategy-foot"));
  assert.ok(component.includes("portfolio-koers-cockpit-sr"));
  assert.ok(css.includes(".portfolio-strategy-foot"));
  assert.ok(css.includes(".portfolio-koers-cockpit-sr"));
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


test("Build 417 removes the old instruction button and global seat mutation entirely",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.equal(component.includes("longSlots:targetLong"),false);
  assert.equal(component.includes("shortSlots:targetShort"),false);
  assert.equal(component.includes("maximumPositions:targetLong+targetShort"),false);
  assert.equal(component.includes("applySoldierInstruction"),false);
  assert.ok(component.includes("Portfolio Koers blijft informatief"));
});

