import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { mergePortfolioKoersMarkers, normalizePortfolioKoersPayload } from "../lib/portfolio-koers-chart.mjs";

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
  assert.ok(component.includes("markerRowsRef.current.flatMap((row)=>"));
  assert.ok(component.includes("delta<=markerStep"));
  assert.ok(component.includes("markerTime:row.time"));
  assert.ok(component.includes("time:renderTime"));
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
  assert.ok(component.includes('["DCA","ADD"].includes(String(trade.activityType||"").toUpperCase())'));
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
  assert.ok(component.includes('["DCA","ADD"].includes(String(trade.activityType||"").toUpperCase())'));
  assert.ok(component.includes('title="Gebruikte margin"'));
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


test("Build 519 blocks legacy backend phantom DCA audit rows without stable execution proof",()=>{
  const normalized=normalizePortfolioKoersPayload({
    timeframe:"15m",
    markers:[{
      time:1760,atMs:1_760_000,kind:"entry",side:"LONG",count:12,source:"strategy2-confirmed-audit",
      activityTypes:["DCA"],
      entries:Array.from({length:12},(_,index)=>({
        symbol:"PONSUSDT",side:"LONG",atMs:1_760_000+index*60_000,entryPrice:0.3701,
        activityType:"DCA",exchangeConfirmed:true,orderId:"",clientOrderId:"",
      })),
    }],
  });
  assert.equal(normalized.markers.length,0);
});

test("Build 519 derives live audit marker count from unique execution-proven entries",()=>{
  const normalized=normalizePortfolioKoersPayload({
    timeframe:"15m",
    markers:[{
      time:1760,atMs:1_760_000,kind:"entry",side:"LONG",count:12,source:"strategy2-confirmed-audit",
      activityTypes:["DCA"],
      entries:[
        {symbol:"PONSUSDT",side:"LONG",atMs:1_760_100,entryPrice:0.3701,activityType:"DCA",exchangeConfirmed:true,orderId:"pons-5"},
        {symbol:"PONSUSDT",side:"LONG",atMs:1_760_200,entryPrice:0.3701,activityType:"DCA",exchangeConfirmed:true,orderId:"pons-5"},
      ],
    }],
  });
  assert.equal(normalized.markers.length,1);
  assert.equal(normalized.markers[0].count,2);
});


test("Build 568 shows entry margin dollars without duplicate ENTRY labels and increases 15m candle density",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes('"15m":{visibleBars:42,barSpacing:5.4,rightOffset:1.6}'));
  assert.ok(component.includes('title="Gebruikte margin"'));
  assert.ok(component.includes('trade.marginUsd?accountUsd(trade.marginUsd):"—"'));
  assert.equal(component.includes('trade.activityType==="DCA"?"DCA":trade.activityType==="ADD"?"ADD":"ENTRY"'),false);
  assert.ok(component.includes('["DCA","ADD"].includes(String(trade.activityType||"").toUpperCase())'));
});

test("Build 568 preserves marginUsd in exact marker entry details",()=>{
  const normalized=normalizePortfolioKoersPayload({
    timeframe:"15m",
    markers:[{
      time:900,atMs:900000,kind:"entry",side:"LONG",count:1,source:"strategy2-confirmed-audit",
      entries:[{symbol:"BTCUSDT",side:"LONG",atMs:901000,activityType:"ENTRY",marginUsd:0.4,orderId:"o-568",exchangeConfirmed:true}],
    }],
  });
  assert.equal(normalized.markers[0].entries[0].marginUsd,0.4);
});


test("Build 569 shows explicit unavailable margin instead of an unexplained dash",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes('Margin niet beschikbaar'));
  assert.ok(component.includes('Historisch execution-cluster · niet huidige open posities'));
});

test("Build 569 merged entry marker count equals unique confirmed detail rows",()=>{
  const rows=mergePortfolioKoersMarkers(
    [{time:60,atMs:60_000,kind:"entry",side:"LONG",count:9,source:"aster-confirmed-fills",entries:[
      {symbol:"BTCUSDT",side:"LONG",atMs:61_000,activityType:"ENTRY",orderId:"order-1",exchangeConfirmed:true,marginUsd:.4},
    ]}],
    [{time:60,atMs:60_000,kind:"entry",side:"LONG",count:9,source:"strategy2-confirmed-audit",entries:[
      {symbol:"BTCUSDT",side:"LONG",atMs:62_000,activityType:"ENTRY",orderId:"order-1",exchangeConfirmed:true,marginUsd:.4},
      {symbol:"ETHUSDT",side:"LONG",atMs:63_000,activityType:"ENTRY",orderId:"order-2",exchangeConfirmed:true,marginUsd:.4},
    ]}],
  );
  assert.equal(rows[0].entries.length,2);
  assert.equal(rows[0].count,2);
});

test("Build 569 cold start focuses the latest contiguous real candle run",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("contiguousStartupCandles=viewMode===\"account\"?latestContiguousPortfolioCandles(candles,timeframe):candles"));
  assert.ok(component.includes("candles.length-accountStartupVisibleBars-.5"));
});
