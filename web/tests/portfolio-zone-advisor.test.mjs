import assert from "node:assert/strict";
import test from "node:test";
import { derivePortfolioZoneInstruction, PORTFOLIO_ZONE_SEATS_PER_STEP } from "../lib/portfolio-zone-advisor.mjs";

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
