import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { derivePortfolioZoneLadder, extendPortfolioZoneLadderToPrice, extendPortfolioZoneLadderToRange, portfolioZoneContextFromLadder, PORTFOLIO_ZONE_DISPLAY_MAX_ZONES } from "../lib/portfolio-zone-advisor.mjs";

const component=()=>readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");

// Ladder like the live account: ~0.29% steps around $248, active zone -6.
const liveLadder=()=>{
  const base=derivePortfolioZoneLadder([
    {index:-1,center:251.6,atr:.5},{index:0,center:252.33,atr:.5},{index:1,center:253.06,atr:.5},
  ]);
  return extendPortfolioZoneLadderToPrice(base,248.07,18);
};

test("Build 635 display ladder covers the whole price history, not only ±6 zones",()=>{
  const ladder=liveLadder();
  const top=Math.max(...ladder.zones.map((row)=>Number(row.center)));
  assert.ok(top<262,"old ladder stops well below the $280 history");
  const display=extendPortfolioZoneLadderToRange(ladder,236,284,{focusPrice:248.07});
  const finite=display.zones.filter((row)=>Number.isFinite(row.upper)&&Number.isFinite(row.lower));
  assert.ok(display.zones.at(-1).center>=284);
  assert.ok(display.zones[0].center<=236);
  assert.ok(finite.length>40);
  for(let index=1;index<display.zones.length;index+=1){
    assert.ok(display.zones[index].center>display.zones[index-1].center,"monotonic centers");
    assert.equal(display.zones[index].index,display.zones[index-1].index+1);
  }
});

test("Build 635 display ladder keeps the same step, anchor, confirmed centers and active zone",()=>{
  const ladder=liveLadder();
  const display=extendPortfolioZoneLadderToRange(ladder,236,284,{focusPrice:248.07});
  assert.equal(display.step,ladder.step);
  assert.equal(display.anchor,ladder.anchor);
  for(const row of ladder.zones){
    const same=display.zones.find((item)=>item.index===row.index);
    assert.ok(same,`zone ${row.index} kept`);
    assert.equal(same.center,row.center);
  }
  assert.equal(portfolioZoneContextFromLadder(display,248.07).activeIndex,portfolioZoneContextFromLadder(ladder,248.07).activeIndex);
});

test("Build 635 display ladder is capped and centred on the live price",()=>{
  const display=extendPortfolioZoneLadderToRange(liveLadder(),20,5000,{focusPrice:248.07});
  assert.ok(display.zones.length<=PORTFOLIO_ZONE_DISPLAY_MAX_ZONES);
  assert.ok(display.zones.some((row)=>row.lower<=248.07&&row.upper>248.07));
});

test("Build 635 display ladder ignores invalid input",()=>{
  const ladder=liveLadder();
  assert.equal(extendPortfolioZoneLadderToRange(ladder,null,284),ladder);
  assert.equal(extendPortfolioZoneLadderToRange(ladder,290,280),ladder);
  assert.equal(extendPortfolioZoneLadderToRange({zones:[]},200,300).zones.length,0);
});

test("Build 635 a tap never parks the crosshair and blocks the next drag",async()=>{
  const source=await component();
  assert.ok(source.includes("trackingMode:{exitMode:TrackingModeExitMode.OnTouchEnd}"));
  assert.ok(source.includes("TrackingModeExitMode, createChart"));
  assert.ok(source.includes("horzTouchDrag:true,vertTouchDrag:true"));
});

test("Build 635 the 45 s refresh waits for the finger and keeps a manual price zoom",async()=>{
  const source=await component();
  assert.ok(source.includes("if(chartInteractingRef.current&&Date.now()-chartInteractingRef.current<15_000)pendingPayloadRef.current=normalized;"));
  assert.ok(source.includes('window.addEventListener("touchend",endInteraction,{passive:true});'));
  assert.ok(source.includes('window.removeEventListener("touchend",endInteraction)'));
  assert.ok(source.includes("if(pending){pendingPayloadRef.current=null;setPayload(pending)}"));
  assert.ok(source.includes("savedPriceScaleRef.current[viewportKey]={from:Number(range.from),to:Number(range.to)}"));
  assert.ok(source.includes("priceScale.setAutoScale(false);priceScale.setVisibleRange(savedPriceRange)"));
});

test("Build 635 zone lines are drawn over the full display ladder without a 48-line cap",async()=>{
  const source=await component();
  assert.ok(source.includes("advisorZoneLadderRef.current=displayZoneLadder;"));
  assert.ok(source.includes("const lineLadder=advisorZoneLadderRef.current;"));
  assert.equal(source.includes("prices.slice(-48)"),false);
  // Trading/advisor zone context still uses the original strategy ladder.
  assert.ok(source.includes("portfolioZoneContextFromLadder(chartZoneLadder,currentZonePrice)"));
});

test("Build 635 every timeframe opens like 15m",async()=>{
  const source=await component();
  for(const pair of ['"15m":{visibleBars:42,barSpacing:5.4,rightOffset:1.6}','"1u":{visibleBars:42,barSpacing:5.4,rightOffset:1.6}','"4u":{visibleBars:42,barSpacing:5.4,rightOffset:1.6}']) assert.ok(source.includes(pair),pair);
  assert.equal(source.includes("Math.max(-.5,candles.length-accountStartupVisibleBars-.5)"),false);
});

test("Build 635 Nu-button resets to the latest candle and auto price scale",async()=>{
  const source=await component();
  assert.ok(source.includes('className={`portfolio-koers-now ${awayFromNow?"is-visible":""}`}'));
  assert.ok(source.includes("priceScale.setAutoScale(true);"));
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(css.includes(".portfolio-koers-now.is-visible{opacity:1;transform:none;pointer-events:auto;cursor:pointer}"));
});
