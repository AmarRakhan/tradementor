import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { mergePortfolioKoersMarkers } from "../lib/portfolio-koers-chart.mjs";

test("live audit markers merge with durable fill markers without visual duplicates",()=>{
  const rows=mergePortfolioKoersMarkers(
    [{time:60,atMs:60_000,kind:"entry",side:"SHORT",count:1,notionalUsd:25,source:"aster-confirmed-fills",label:"ENTRY S · $25.00"}],
    [{time:60,atMs:60_000,kind:"entry",side:"SHORT",count:1,source:"strategy2-confirmed-audit",activityTypes:["ENTRY"],originZones:[-2]}],
  );
  assert.equal(rows.length,1);
  assert.equal(rows[0].count,1);
  assert.equal(rows[0].notionalUsd,25);
  assert.deepEqual(rows[0].originZones,[-2]);
  assert.deepEqual(rows[0].activityTypes,["ENTRY"]);
  assert.equal(rows[0].source,"aster-confirmed-fills");
});

test("multiple same-minute audit actions stay one visible marker with the highest confirmed count",()=>{
  const rows=mergePortfolioKoersMarkers(
    [],
    [
      {time:60,atMs:60_000,kind:"entry",side:"LONG",count:1,source:"strategy2-confirmed-audit",activityTypes:["ENTRY"]},
      {time:60,atMs:60_000,kind:"entry",side:"LONG",count:2,source:"strategy2-confirmed-audit",activityTypes:["DCA"]},
    ],
  );
  assert.equal(rows.length,1);
  assert.equal(rows[0].count,2);
  assert.deepEqual(rows[0].activityTypes,["DCA","ENTRY"]);
});

test("Portfolio Koers uses a lightweight five-second marker feed and rebuilds only when cashflow adjustment changes",async()=>{
  const [component,route]=await Promise.all([
    readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8"),
    readFile(new URL("../app/api/exchanges/aster/portfolio-chart/events/route.ts",import.meta.url),"utf8"),
  ]);
  assert.ok(component.includes("/api/exchanges/aster/portfolio-chart/events?timeframe="));
  assert.ok(component.includes("},5_000);"));
  assert.ok(component.includes("const markerRowsRef=useRef<Marker[]>([])"));
  assert.ok(component.includes("markerRowsRef.current.filter((row)=>candleByTime.has(row.time))"));
  assert.ok(component.includes("setHover({candle,markers:markerRowsRef.current.filter((row)=>row.time===time)})"));
  assert.ok(component.includes("},[baseCandles,activeCandles,payload.zones,payload.cycleStartEquity,timeframe,viewMode,cashflowSignature]);"));
  assert.equal(component.includes("},[baseCandles,activeCandles,payload.markers,payload.zones,payload.cycleStartEquity,timeframe,viewMode,cashflowSignature]);"),false);
  assert.ok(component.includes("const cashflowSignature=useMemo"));
  assert.ok(route.includes("/v1/me/aster/portfolio-chart/events"));
});

test("Build 514 keeps the exact Strategy-2 audit rows behind a merged LONG/SHORT cluster",()=>{
  const rows=mergePortfolioKoersMarkers(
    [{time:60,atMs:60_000,kind:"entry",side:"SHORT",count:1,notionalUsd:25,source:"aster-confirmed-fills",label:"ENTRY S"}],
    [{time:60,atMs:60_000,kind:"entry",side:"SHORT",count:2,source:"strategy2-confirmed-audit",entries:[
      {symbol:"BTCUSDT",side:"SHORT",atMs:61_000,entryPrice:null,notionalUsd:12,activityType:"ENTRY",originZone:2,soldierId:"S-1",soldierRole:"ZONE_BASE"},
      {symbol:"ETHUSDT",side:"SHORT",atMs:65_000,entryPrice:2500,notionalUsd:null,activityType:"DCA",originZone:2,soldierId:"S-2",soldierRole:"ZONE_BASE"},
    ]}],
  );
  assert.equal(rows.length,1);
  assert.equal(rows[0].count,2);
  assert.equal(rows[0].entries.length,2);
  assert.deepEqual(rows[0].entries.map((row)=>row.symbol),["BTCUSDT","ETHUSDT"]);
  assert.equal(rows[0].entries[1].entryPrice,2500);
});

test("Build 514 opens entry clusters from marker-owned details before using the old activity fallback",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("const exactMarkerEntries=!isTp?markerEntryTrades(label.entries):[]"));
  assert.ok(component.includes("if(!isTp&&exactMarkerEntries.length===expected)"));
  assert.ok(component.includes("setSelectedTpCluster({...label,trades:exactMarkerEntries})"));
  assert.ok(component.includes("entries:Array.isArray(row.entries)?row.entries:[]"));
});


test("Build 515 makes the LONG/SHORT entry-event panel scrollable and labels repeated rows truthfully",async()=>{
  const [component,css]=await Promise.all([
    readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8"),
    readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8"),
  ]);
  assert.ok(component.includes("entry-events"));
  assert.ok(component.includes('trade.activityType==="DCA"?"DCA":trade.activityType==="ADD"?"ADD":"ENTRY"'));
  assert.ok(component.includes('row.entryPrice??row.averagePrice??row.avgPrice??row.price'));
  assert.ok(component.includes('row.executedNotionalUsd??row.notionalUsd??row.notional'));
  assert.ok(css.includes(".portfolio-koers-tp-trades{display:grid;min-height:0;overflow-y:auto"));
  assert.ok(css.includes("-webkit-overflow-scrolling:touch"));
  assert.ok(css.includes("touch-action:pan-y"));
});


test("Build 516 distinguishes reconciled ADD events from true DCA and preserves DCA proof metadata",async()=>{
  const [component,lib]=await Promise.all([
    readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8"),
    readFile(new URL("../lib/portfolio-koers-chart.mjs",import.meta.url),"utf8"),
  ]);
  assert.ok(component.includes('trade.activityType==="ADD"?"ADD":"ENTRY"'));
  assert.ok(component.includes("entryPriceText(trade.entryPrice)"));
  for(const token of ["dcaNumber","dcaDistancePercent","anchorPrice","triggerPrice","fillQuantity","orderId","clientOrderId","exchangeConfirmed"]){
    assert.ok(lib.includes(token),token);
  }
});


test("Build 517 deduplicates repeated entry details by stable execution identity",()=>{
  const rows=mergePortfolioKoersMarkers(
    [{time:60,atMs:60_000,kind:"entry",side:"LONG",count:1,source:"aster-confirmed-fills",entries:[
      {symbol:"PONSUSDT",side:"LONG",atMs:61_000,activityType:"DCA",orderId:"pons-5",exchangeConfirmed:true},
    ]}],
    [{time:60,atMs:60_000,kind:"entry",side:"LONG",count:1,source:"strategy2-confirmed-audit",entries:[
      {symbol:"PONSUSDT",side:"LONG",atMs:63_000,activityType:"DCA",orderId:"pons-5",exchangeConfirmed:true},
    ]}],
  );
  assert.equal(rows.length,1);
  assert.equal(rows[0].entries.length,1);
  assert.equal(rows[0].entries[0].orderId,"pons-5");
});
