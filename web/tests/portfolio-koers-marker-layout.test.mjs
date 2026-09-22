import assert from "node:assert/strict";
import test from "node:test";
import {
  eventPriority,
  layoutPortfolioKoersMarkers,
  markerRectInsideBollinger,
  markerRectsOverlap,
  MAX_COMPACT_EVENT_CLUSTERS,
  MAX_FULL_EVENT_LABELS,
  zoneToneForRank,
} from "../lib/portfolio-koers-marker-layout.mjs";

function candidate(index,{x=80+index*18,y=120,kind="entry",time=1_700_000_000+index,eventCount=1,position=index%2?"below":"above",bandTop=82,bandBottom=150}={}) {
  return {
    id:`e${index}`,x,y,position,kind,time,eventCount,
    priority:eventPriority({kind}),tone:kind==="tp"?"tp":"long",
    glyph:kind==="tp"?"💰":"♟",multiplier:eventCount>1?`×${eventCount}`:"",
    title:`E${index}`,value:"",width:36,height:22,bandTop,bandBottom,
    anchorLeft:x,anchorTop:y,
  };
}

test("dense events remain capped at three icon labels and two compact clusters",()=>{
  const rows=Array.from({length:20},(_,index)=>candidate(index,{
    x:55+(index%10)*30,y:115+(index%3)*5,
    kind:index%3===0?"tp":"entry",position:index%2?"below":"above",
  }));
  const layout=layoutPortfolioKoersMarkers(rows,{width:620,height:260});
  assert.ok(layout.full.length<=MAX_FULL_EVENT_LABELS);
  assert.ok(layout.compact.length<=MAX_COMPACT_EVENT_CLUSTERS);
  assert.ok(layout.all.length<=MAX_FULL_EVENT_LABELS+MAX_COMPACT_EVENT_CLUSTERS);
});

test("full marker rectangles never overlap",()=>{
  const rows=Array.from({length:8},(_,index)=>candidate(index,{x:180,y:110+index*2,kind:"entry",position:"below"}));
  const layout=layoutPortfolioKoersMarkers(rows,{width:520,height:240});
  assert.equal(markerRectsOverlap(layout.all),false);
});

test("markers with confirmed Bollinger coordinates stay outside the envelope",()=>{
  const rows=[
    candidate(0,{x:100,y:110,position:"above",bandTop:80,bandBottom:150}),
    candidate(1,{x:190,y:115,position:"below",bandTop:82,bandBottom:152}),
    candidate(2,{x:280,y:118,position:"above",bandTop:84,bandBottom:154,kind:"tp"}),
  ];
  const layout=layoutPortfolioKoersMarkers(rows,{width:420,height:220});
  assert.ok(layout.full.length>0);
  for(const label of layout.full){
    assert.equal(markerRectInsideBollinger(label,4),false);
    if(label.position==="above")assert.ok(label.rect.bottom<=label.bandTop-4);
    if(label.position==="below")assert.ok(label.rect.top>=label.bandBottom+4);
  }
});

test("cluster keeps hidden event counts without inventing events",()=>{
  const rows=Array.from({length:9},(_,index)=>candidate(index,{x:90+index*16,y:115,eventCount:index===0?3:1,position:index%2?"below":"above"}));
  const layout=layoutPortfolioKoersMarkers(rows,{width:390,height:230},{maxFull:1,maxCompact:2,priceAxisWidth:48});
  const shown=layout.full.reduce((sum,row)=>sum+row.eventCount,0)+layout.compact.reduce((sum,row)=>sum+row.eventCount,0);
  const expected=rows.reduce((sum,row)=>sum+row.eventCount,0);
  assert.equal(shown,expected);
});

test("entry markers remain prioritized above TP and cashflow under density",()=>{
  assert.ok(eventPriority({kind:"entry"})>eventPriority({kind:"tp"}));
  assert.ok(eventPriority({kind:"tp"})>eventPriority({kind:"cashflow"}));
});

test("price axis reservation defaults to the narrower mobile contract",()=>{
  const row=candidate(0,{x:335,y:120,position:"below"});
  const layout=layoutPortfolioKoersMarkers([row],{width:390,height:230});
  assert.equal(layout.full.length,1);
  assert.ok(layout.full[0].rect.right<=390-48-3);
});

test("zone palette follows top red, amber, green, bottom blue order",()=>{
  assert.equal(zoneToneForRank(0,4),"red");
  assert.equal(zoneToneForRank(1,4),"amber");
  assert.equal(zoneToneForRank(2,4),"green");
  assert.equal(zoneToneForRank(3,4),"blue");
});
