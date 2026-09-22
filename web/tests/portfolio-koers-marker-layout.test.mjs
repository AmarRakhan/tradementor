import assert from "node:assert/strict";
import test from "node:test";
import { eventPriority, layoutPortfolioKoersMarkers, markerRectsOverlap, MAX_FULL_EVENT_LABELS, zoneToneForRank } from "../lib/portfolio-koers-marker-layout.mjs";

function candidate(index,{x=80+index*18,y=120,kind="entry",time=1_700_000_000+index,eventCount=1}={}) {
  return {id:`e${index}`,x,y,position:index%2?"below":"above",kind,time,eventCount,priority:eventPriority({kind}),tone:kind==="tp"?"tp":"long",title:`E${index}`,value:"$ 1,00"};
}

test("20 visible events never produce more than five full labels",()=>{
  const rows=Array.from({length:20},(_,index)=>candidate(index,{x:70+(index%10)*28,y:80+(index%3)*36,kind:index%3===0?"tp":"entry"}));
  const layout=layoutPortfolioKoersMarkers(rows,{width:620,height:260});
  assert.ok(layout.full.length<=MAX_FULL_EVENT_LABELS);
  assert.equal(layout.full.length,5);
  assert.ok(layout.compact.length>0);
});

test("collision layout never leaves full label rectangles overlapping",()=>{
  const rows=Array.from({length:8},(_,index)=>candidate(index,{x:180,y:110+index*2,kind:"entry"}));
  const layout=layoutPortfolioKoersMarkers(rows,{width:520,height:240});
  assert.equal(markerRectsOverlap(layout.full),false);
  assert.ok(layout.compact.length>0);
});

test("cluster keeps all hidden event counts without inventing events",()=>{
  const rows=Array.from({length:7},(_,index)=>candidate(index,{x:120+index,y:100+index,eventCount:index===0?2:1}));
  const layout=layoutPortfolioKoersMarkers(rows,{width:360,height:210},{maxFull:1});
  const hiddenCount=layout.compact.reduce((sum,row)=>sum+row.eventCount,0);
  const fullCount=layout.full.reduce((sum,row)=>sum+row.eventCount,0);
  assert.equal(hiddenCount+fullCount,8);
  assert.ok(layout.compact.every((row)=>row.title===`+${row.eventCount} events`));
});

test("entry labels are prioritized above TP and cashflow when density is high",()=>{
  assert.ok(eventPriority({kind:"entry"})>eventPriority({kind:"tp"}));
  assert.ok(eventPriority({kind:"tp"})>eventPriority({kind:"cashflow"}));
});

test("zone palette follows top red, amber, green, bottom blue order",()=>{
  assert.equal(zoneToneForRank(0,4),"red");
  assert.equal(zoneToneForRank(1,4),"amber");
  assert.equal(zoneToneForRank(2,4),"green");
  assert.equal(zoneToneForRank(3,4),"blue");
});
