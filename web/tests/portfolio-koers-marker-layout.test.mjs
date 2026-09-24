import assert from "node:assert/strict";
import test from "node:test";
import {
  EVENT_MARKER_SAFETY_CAP,
  eventPriority,
  layoutPortfolioKoersMarkers,
  layoutPortfolioKoersZoneRegions,
  markerRectInsideBollinger,
  markerRectsOverlap,
  zoneToneForRank,
} from "../lib/portfolio-koers-marker-layout.mjs";

function candidate(index,{x=80+index*42,y=120,kind="entry",time=1_700_000_000+index,eventCount=1,position=index%2?"below":"above",bandTop=82,bandBottom=150}={}) {
  return {
    id:`e${index}`,x,y,position,kind,time,eventCount,
    priority:eventPriority({kind}),tone:kind==="tp"?"tp":"long",
    glyph:kind==="tp"?"💰":"⚔",multiplier:`×${eventCount}`,
    title:`E${index}`,value:"",width:48,height:44,bandTop,bandBottom,
    anchorLeft:x,anchorTop:y,
  };
}

test("six visible event candles produce six candle-bound labels instead of a global top-three",()=>{
  const rows=Array.from({length:6},(_,index)=>candidate(index,{x:55+index*80,y:112,position:index%2?"below":"above"}));
  const layout=layoutPortfolioKoersMarkers(rows,{width:620,height:318});
  assert.equal(layout.all.length,6);
  assert.deepEqual(layout.all.map((row)=>row.id).sort(),rows.map((row)=>row.id).sort());
  assert.equal(layout.compact.length,0);
  assert.equal(layout.safetyCapApplied,false);
});

test("twenty normal visible events remain represented one-for-one",()=>{
  const rows=Array.from({length:20},(_,index)=>candidate(index,{
    x:42+(index%10)*52,y:110+(index%3)*4,time:1_700_000_000+index,
    kind:index%3===0?"tp":"entry",position:index%2?"below":"above",
  }));
  const layout=layoutPortfolioKoersMarkers(rows,{width:620,height:318});
  assert.equal(layout.all.length,20);
  assert.equal(new Set(layout.all.map((row)=>row.id)).size,20);
  assert.equal(layout.safetyCapApplied,false);
});

test("multiple events on one candle stack locally without merging their event counts",()=>{
  const rows=[
    candidate(0,{x:210,time:1234,position:"above",kind:"entry",eventCount:2}),
    candidate(1,{x:210,time:1234,position:"below",kind:"entry",eventCount:1}),
    candidate(2,{x:210,time:1234,position:"above",kind:"tp",eventCount:2}),
  ];
  const layout=layoutPortfolioKoersMarkers(rows,{width:480,height:318});
  assert.equal(layout.all.length,3);
  assert.deepEqual(layout.all.map((row)=>row.eventCount).sort((a,b)=>a-b),[1,2,2]);
  assert.ok(layout.all.every((row)=>row.time===1234));
});

test("spaced full marker rectangles do not overlap",()=>{
  const rows=Array.from({length:6},(_,index)=>candidate(index,{x:55+index*75,y:115,position:index%2?"below":"above"}));
  const layout=layoutPortfolioKoersMarkers(rows,{width:560,height:318});
  assert.equal(markerRectsOverlap(layout.all),false);
});

test("markers with confirmed Bollinger coordinates stay outside the envelope when geometry allows",()=>{
  const rows=[
    candidate(0,{x:100,y:110,position:"above",bandTop:80,bandBottom:150}),
    candidate(1,{x:230,y:115,position:"below",bandTop:82,bandBottom:152}),
    candidate(2,{x:360,y:118,position:"above",bandTop:84,bandBottom:154,kind:"tp"}),
  ];
  const layout=layoutPortfolioKoersMarkers(rows,{width:480,height:318});
  assert.equal(layout.all.length,3);
  for(const label of layout.all){
    assert.equal(markerRectInsideBollinger(label,3),false);
    if(label.position==="above")assert.ok(label.rect.bottom<=label.bandTop-3);
    if(label.position==="below")assert.ok(label.rect.top>=label.bandBottom+3);
  }
});

test("the corruption safety cap is high and not a normal density limit",()=>{
  assert.ok(EVENT_MARKER_SAFETY_CAP>=100);
  const rows=Array.from({length:EVENT_MARKER_SAFETY_CAP+8},(_,index)=>candidate(index,{x:100+(index%12)*25,time:10_000+index,position:index%2?"below":"above"}));
  const layout=layoutPortfolioKoersMarkers(rows,{width:620,height:318});
  assert.equal(layout.all.length,EVENT_MARKER_SAFETY_CAP);
  assert.equal(layout.safetyCapApplied,true);
});

test("entry markers remain prioritized above TP and cashflow for local placement only",()=>{
  assert.ok(eventPriority({kind:"entry"})>eventPriority({kind:"tp"}));
  assert.ok(eventPriority({kind:"tp"})>eventPriority({kind:"cashflow"}));
});

test("price axis reservation defaults to the narrower mobile contract",()=>{
  const row=candidate(0,{x:335,y:120,position:"below"});
  const layout=layoutPortfolioKoersMarkers([row],{width:390,height:286});
  assert.equal(layout.all.length,1);
  assert.ok(layout.all[0].rect.right<=390-48-3);
});

test("zone palette follows top red, amber, green, bottom blue order",()=>{
  assert.equal(zoneToneForRank(0,4),"red");
  assert.equal(zoneToneForRank(1,4),"amber");
  assert.equal(zoneToneForRank(2,4),"green");
  assert.equal(zoneToneForRank(3,4),"blue");
});

test("real zone centers expand into contiguous reference-style value regions",()=>{
  const regions=layoutPortfolioKoersZoneRegions([
    {index:2,label:"Zone +2",centerY:48,upperY:40,lowerY:56,source:"confirmed-swings+sr-cluster+atr"},
    {index:1,label:"Zone +1",centerY:112,upperY:104,lowerY:120,source:"confirmed-swings+sr-cluster+atr"},
    {index:0,label:"Zone 0",centerY:182,upperY:174,lowerY:190,source:"confirmed-swings+sr-cluster+atr"},
    {index:-1,label:"Zone -1",centerY:250,upperY:242,lowerY:258,source:"confirmed-swings+sr-cluster+atr"},
  ],300);
  assert.equal(regions.length,4);
  assert.equal(regions[0].tone,"red");
  assert.equal(regions[1].tone,"amber");
  assert.equal(regions[2].tone,"green");
  assert.equal(regions[3].tone,"blue");
  assert.equal(regions[0].top,40);
  assert.equal(regions[0].height,40);
  assert.equal(regions[1].top,80);
  assert.equal(regions[1].height,67);
  assert.ok(regions.every((row)=>row.regionSource==="confirmed-zone-centers"));
  assert.ok(regions.every((row)=>row.source==="confirmed-swings+sr-cluster+atr"));
});

test("a single confirmed zone keeps its real upper and lower edges",()=>{
  const [region]=layoutPortfolioKoersZoneRegions([
    {index:0,label:"Zone 0",centerY:120,upperY:110,lowerY:132,source:"confirmed-swings+sr-cluster+atr"},
  ],300);
  assert.equal(region.top,110);
  assert.equal(region.height,22);
});
