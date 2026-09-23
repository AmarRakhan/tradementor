import assert from "node:assert/strict";
import test from "node:test";
import { derivePortfolioZoneInstruction, derivePortfolioZoneLadder, portfolioZoneFromLadder, portfolioZoneContextFromLadder, zoneToneForSignedIndex, PORTFOLIO_ZONE_SEATS_PER_STEP } from "../lib/portfolio-zone-advisor.mjs";

test("zone +2 asks for ten free SHORT soldiers exactly like the approved reference",()=>{
  assert.equal(PORTFOLIO_ZONE_SEATS_PER_STEP,5);
  const row=derivePortfolioZoneInstruction({zoneIndex:2,longSlots:60,shortSlots:30,activeLong:60,activeShort:30});
  assert.equal(row.status,"ADD");
  assert.equal(row.side,"SHORT");
  assert.equal(row.amount,10);
  assert.equal(row.targetLongSlots,60);
  assert.equal(row.targetShortSlots,40);
  assert.equal(row.desiredShortSlots,40);
});

test("returning from a higher positive zone can call unused SHORT soldiers home without closing positions",()=>{
  const row=derivePortfolioZoneInstruction({zoneIndex:1,longSlots:60,shortSlots:40,activeLong:60,activeShort:30});
  assert.equal(row.status,"REMOVE");
  assert.equal(row.side,"SHORT");
  assert.equal(row.amount,5);
  assert.equal(row.targetShortSlots,35);
  assert.ok(row.targetShortSlots>=row.activeShort);
});

test("negative zones reserve free LONG soldiers",()=>{
  const row=derivePortfolioZoneInstruction({zoneIndex:-2,longSlots:55,shortSlots:30,activeLong:50,activeShort:30});
  assert.equal(row.status,"ADD");
  assert.equal(row.side,"LONG");
  assert.equal(row.amount,5);
  assert.equal(row.targetLongSlots,60);
});

test("zone zero keeps the existing formation",()=>{
  const row=derivePortfolioZoneInstruction({zoneIndex:0,longSlots:60,shortSlots:40,activeLong:55,activeShort:30});
  assert.equal(row.status,"OK");
  assert.equal(row.side,null);
  assert.equal(row.targetLongSlots,60);
  assert.equal(row.targetShortSlots,40);
});

test("advisor never grows beyond the hard total slot ceiling",()=>{
  const row=derivePortfolioZoneInstruction({zoneIndex:2,longSlots:70,shortSlots:30,activeLong:70,activeShort:30});
  assert.equal(row.status,"BLOCKED");
  assert.equal(row.targetLongSlots,70);
  assert.equal(row.targetShortSlots,30);
});

test("advisor refuses to invent an instruction when live occupancy is missing",()=>{
  const row=derivePortfolioZoneInstruction({zoneIndex:2,longSlots:60,shortSlots:30,activeLong:null,activeShort:30});
  assert.equal(row.status,"UNAVAILABLE");
});


test("advisor refuses to invent zone zero when the current zone is missing",()=>{
  const row=derivePortfolioZoneInstruction({zoneIndex:null,longSlots:60,shortSlots:30,activeLong:60,activeShort:30});
  assert.equal(row.status,"UNAVAILABLE");
  assert.equal(row.zoneIndex,null);
});


test("confirmed zone centers are extended to a complete -3 through +3 ladder",()=>{
  const ladder=derivePortfolioZoneLadder([
    {index:-1,center:100,atr:3},
    {index:0,center:105,atr:3},
  ]);
  assert.deepEqual(ladder.zones.map((row)=>row.index),[-3,-2,-1,0,1,2,3]);
  assert.equal(ladder.step,5);
  assert.equal(ladder.anchor,105);
  assert.equal(ladder.zones.find((row)=>row.index===1)?.center,110);
  assert.equal(ladder.zones.find((row)=>row.index===3)?.upper,Infinity);
});

test("price far above the highest confirmed zone becomes a positive extrapolated zone instead of zone zero",()=>{
  const ladder=derivePortfolioZoneLadder([
    {index:-1,center:100,atr:3},
    {index:0,center:105,atr:3},
  ]);
  assert.equal(portfolioZoneFromLadder(ladder,141.18),3);
  assert.equal(portfolioZoneFromLadder(ladder,111),1);
  assert.equal(portfolioZoneFromLadder(ladder,106),0);
});

test("price below the lowest confirmed zone extrapolates toward LONG zones",()=>{
  const ladder=derivePortfolioZoneLadder([
    {index:0,center:105,atr:3},
    {index:1,center:110,atr:3},
  ]);
  assert.equal(portfolioZoneFromLadder(ladder,86),-3);
  assert.equal(portfolioZoneFromLadder(ladder,101),-1);
});

test("signed zone tones match the approved high-to-low visual hierarchy",()=>{
  assert.equal(zoneToneForSignedIndex(3),"red");
  assert.equal(zoneToneForSignedIndex(2),"amber");
  assert.equal(zoneToneForSignedIndex(1),"amber");
  assert.equal(zoneToneForSignedIndex(0),"blue");
  assert.equal(zoneToneForSignedIndex(-1),"green");
  assert.equal(zoneToneForSignedIndex(-3),"green");
});

test("single confirmed zone can safely use ATR fallback spacing",()=>{
  const ladder=derivePortfolioZoneLadder([{index:0,center:100,atr:4}]);
  assert.equal(ladder.source,"atr-fallback-spacing");
  assert.equal(ladder.step,6);
  assert.equal(portfolioZoneFromLadder(ladder,119),3);
});

test("missing zone evidence stays unavailable and does not invent a ladder",()=>{
  const ladder=derivePortfolioZoneLadder([]);
  assert.deepEqual(ladder.zones,[]);
  assert.equal(portfolioZoneFromLadder(ladder,141),null);
});


test("zone decision context exposes the exact next upper and lower trigger",()=>{
  const ladder=derivePortfolioZoneLadder([
    {index:-1,center:100,atr:3},
    {index:0,center:110,atr:3},
    {index:1,center:120,atr:3},
  ]);
  const context=portfolioZoneContextFromLadder(ladder,111);
  assert.equal(context.activeIndex,0);
  assert.equal(context.lowerBoundary,105);
  assert.equal(context.upperBoundary,115);
  assert.equal(context.nextDownIndex,-1);
  assert.equal(context.nextUpIndex,1);
});

test("outer zone context leaves missing next boundary explicit instead of inventing a level",()=>{
  const ladder=derivePortfolioZoneLadder([{index:0,center:100,atr:4}]);
  const context=portfolioZoneContextFromLadder(ladder,500);
  assert.equal(context.activeIndex,3);
  assert.equal(context.upperBoundary,null);
  assert.equal(context.nextUpIndex,null);
  assert.equal(context.nextDownIndex,2);
});
