import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { PORTFOLIO_KOERS_DEFAULT_TIMEFRAME, PORTFOLIO_KOERS_TIMEFRAMES, aggregatePortfolioEquityHistory, bollinger20x2, cashflowAdjustedPortfolioSeries, markerVisual, mergePortfolioKoersCandles, mergePortfolioKoersMarkers, mergeRealtimeEquitySample, normalizePortfolioKoersPayload, parsePortfolioEquityText, portfolioCashflowShift, portfolioKoersFocusBars, portfolioKoersTimelineHealth, portfolioZoneDistancePercent, portfolioZoneForPrice, portfolioZoneProgress, tpTradesForBucketFromActivity } from "../lib/portfolio-koers-chart.mjs";

test("Portfolio Koers exposes only the approved timeframes and defaults to 15m",()=>{
  assert.deepEqual([...PORTFOLIO_KOERS_TIMEFRAMES],["1m","5m","15m","1u","4u","24u"]);
  assert.equal(PORTFOLIO_KOERS_DEFAULT_TIMEFRAME,"15m");
});

test("Portfolio Koers never fabricates invalid or missing candles",()=>{
  assert.deepEqual(normalizePortfolioKoersPayload({candles:[]}).candles,[]);
  const payload=normalizePortfolioKoersPayload({candles:[
    {time:60,open:100,high:102,low:99,close:101},
    {time:120,open:0,high:2,low:1,close:2},
    {time:180,open:100,high:99,low:98,close:100},
  ]});
  assert.equal(payload.candles.length,1);
  assert.equal(payload.candles[0].close,101);
});

test("TP detail rows survive payload normalization and confirmed-fill marker merging",()=>{
  const base=normalizePortfolioKoersPayload({markers:[{
    time:900,atMs:900000,kind:"tp",side:"ALL",count:3,realizedPnlUsd:5,
    trades:[
      {symbol:"BTCUSDT",realizedPnlUsd:1.9,durationMinutes:18},
      {symbol:"ETHUSDT",realizedPnlUsd:2.1,durationMinutes:41},
      {symbol:"XRPUSDT",realizedPnlUsd:1,durationMinutes:12},
    ],
    source:"aster-confirmed-fills",
  }]}).markers;
  assert.deepEqual(base[0].trades.map((row)=>row.symbol),["BTC","ETH","XRP"]);
  const merged=mergePortfolioKoersMarkers([{time:900,kind:"tp",side:"ALL",count:1,source:"strategy2-confirmed-audit"}],base);
  assert.equal(merged[0].realizedPnlUsd,5);
  assert.equal(merged[0].trades.length,3);
});

test("TP detail lazy enrichment reconstructs confirmed symbols, PnL and first-entry duration",()=>{
  const activity={
    entries:[
      {timestampMs:60_000,symbol:"BTCUSDT",side:"LONG",quantity:1},
      {timestampMs:360_000,symbol:"BTCUSDT",side:"LONG",quantity:1},
      {timestampMs:120_000,symbol:"ETHUSDT",side:"SHORT",quantity:2},
    ],
    exits:[
      {timestampMs:1_260_000,symbol:"BTCUSDT",side:"LONG",quantity:2,realizedPnlUsd:1.9},
      {timestampMs:1_320_000,symbol:"ETHUSDT",side:"SHORT",quantity:2,realizedPnlUsd:2.1},
    ],
  };
  const rows=tpTradesForBucketFromActivity(activity,"15m",900);
  assert.deepEqual(rows,[
    {symbol:"BTC",realizedPnlUsd:1.9,durationMinutes:20},
    {symbol:"ETH",realizedPnlUsd:2.1,durationMinutes:20},
  ]);
});

test("Bollinger Bands are exactly period 20 multiplier 2",()=>{
  const candles=Array.from({length:20},(_,index)=>({time:index+1,close:index+1}));
  const bb=bollinger20x2(candles);
  assert.equal(bb.period,20);assert.equal(bb.multiplier,2);assert.equal(bb.middle.length,1);
  assert.equal(bb.middle[0].value,10.5);
  assert.ok(bb.upper[0].value>bb.middle[0].value);
  assert.ok(bb.lower[0].value<bb.middle[0].value);
});

test("Existing confirmed browser Aster equity history can fill the visual chart without inventing values",()=>{
  const rows=[{at:1_800_000,aster:100,total:100},{at:1_860_000,aster:102,total:102},{at:1_980_000,aster:99,total:99}];
  const candles=aggregatePortfolioEquityHistory(rows,"5m",320);
  assert.equal(candles.length,1);
  assert.deepEqual({open:candles[0].open,high:candles[0].high,low:candles[0].low,close:candles[0].close},{open:100,high:102,low:99,close:99});
  const merged=mergePortfolioKoersCandles(candles,[{time:0,open:1,high:1,low:1,close:1},{time:candles[0].time,open:101,high:103,low:98,close:102}],320);
  assert.equal(merged.length,1);
  assert.equal(merged[0].close,102);
});

test("Realtime portfolio samples use only the observed equity value for a new candle",()=>{
  const next=mergeRealtimeEquitySample([{time:60,open:100,high:100,low:99,close:99,atMs:60_000}],105,301_000,"5m");
  assert.equal(next.length,2);
  assert.deepEqual({open:next[1].open,high:next[1].high,low:next[1].low,close:next[1].close},{open:105,high:105,low:105,close:105});
});

test("Portfolio Koers detects a missing 15m run and blocks zone advice until the recent run is long enough",()=>{
  const step=900;
  const broken=[
    {time:step,open:100,high:100,low:100,close:100},
    {time:step*2,open:100,high:100,low:100,close:100},
    {time:step*5,open:101,high:101,low:101,close:101},
    {time:step*6,open:101,high:101,low:101,close:101},
  ];
  const unsafe=portfolioKoersTimelineHealth(broken,"15m",step*6*1000+1_000,14);
  assert.equal(unsafe.gaps.length,1);
  assert.equal(unsafe.gaps[0].missingBars,2);
  assert.equal(unsafe.contiguousBars,2);
  assert.equal(unsafe.safeForAdvisor,false);

  const recovered=[...broken.slice(0,2),...Array.from({length:14},(_,index)=>({
    time:step*(5+index),open:101,high:101,low:101,close:101,
  }))];
  const safe=portfolioKoersTimelineHealth(recovered,"15m",step*18*1000+1_000,14);
  assert.equal(safe.contiguousBars,14);
  assert.equal(safe.safeForAdvisor,true);
});

test("Locale portfolio equity text is parsed without changing its value",()=>{
  assert.equal(parsePortfolioEquityText("US$ 1.234,56"),1234.56);
  assert.equal(parsePortfolioEquityText("$276.42"),276.42);
  assert.equal(parsePortfolioEquityText("—"),null);
});

test("Portfolio Koers keeps the visible Portfolio Snapshot equity authoritative over the chart backend",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.equal(component.includes("if(normalized.currentEquity) setLiveEquity(normalized.currentEquity)"),false);
  assert.ok(component.includes("liveEquityTextRef.current=liveEquityText"));
  assert.ok(component.includes("mergeRealtimeEquitySample(baseCandles,observedEquity"));
});

test("Cashflows remain visually distinct from trading performance markers",()=>{
  assert.equal(markerVisual({kind:"cashflow",label:"TRANSFER +50.00 USD"}).tone,"cashflow");
  assert.equal(markerVisual({kind:"entry",side:"LONG"}).tone,"long");
  assert.equal(markerVisual({kind:"entry",side:"SHORT"}).tone,"short");
  assert.equal(markerVisual({kind:"tp"}).tone,"tp");
});

test("Active zone follows the confirmed zone bands or the nearest confirmed center",()=>{
  const zones=[{index:-1,lower:90,upper:95,center:92.5},{index:0,lower:99,upper:101,center:100},{index:1,lower:105,upper:110,center:107.5}];
  assert.equal(portfolioZoneForPrice(zones,100),0);
  assert.equal(portfolioZoneForPrice(zones,108),1);
  assert.equal(portfolioZoneForPrice(zones,97),0);
});

test("Portfolio Koers lifecycle is mounted inside AuthProvider",async()=>{
  const layout=await readFile(new URL("../app/layout.tsx",import.meta.url),"utf8");
  const providerStart=layout.indexOf("<AuthProvider>");
  const providerEnd=layout.indexOf("</AuthProvider>");
  const enhancer=layout.indexOf("<AsterPortfolioSnapshotEnhancer />");
  assert.ok(providerStart>0);
  assert.ok(enhancer>providerStart);
  assert.ok(providerEnd>enhancer);
});

test("Portfolio Koers is mounted before the existing Portfolio Snapshot and remains read-only",async()=>{
  const source=await readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx",import.meta.url),"utf8");
  const portalStart=source.indexOf("return host ? createPortal");
  const chartMount=source.indexOf("<PortfolioKoersChart",portalStart);
  const snapshotMount=source.indexOf("<Snapshot",chartMount);
  assert.ok(portalStart>0);
  assert.ok(chartMount>portalStart);
  assert.ok(snapshotMount>chartMount);
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("Portfolio Koers"));
  assert.ok(component.includes('viewMode==="active"?"Actieve Trades":"Accountwaarde"'));
  assert.equal(component.includes("Accountwaarde · werkelijke Aster equity"),false);
  assert.ok(component.includes("file_00000000e2fc820a9057c8f60c1ec845"));
  assert.ok(component.includes("file_00000000267082109428370054535e59"));
  assert.ok(component.includes("priceToCoordinate(zone.center)"));
  assert.ok(component.includes("priceToCoordinate(zone.upper)"));
  assert.ok(component.includes("priceToCoordinate(zone.lower)"));
  assert.ok(component.includes("layoutPortfolioKoersZoneRegions"));
  assert.ok(component.includes("layoutPortfolioKoersMarkers"));
  assert.ok(component.includes("getVisibleLogicalRange()"));
  assert.ok(component.includes("visibleMarkerRows"));
  assert.ok(component.includes("selectPortfolioKoersReferenceCandidates(candidates,{tp:4,long:4,short:4,cashflow:1,other:1})"));
  assert.ok(component.includes("safetyCap:12"));
  assert.ok(component.includes("PRICE_AXIS_WIDTH=48"));
  assert.ok(component.includes("attributionLogo:false"));
  assert.equal(/authenticatedRequest\([^)]*method:\s*["']POST/.test(component),false);
});


test("Portfolio Koers UI 4.1 keeps Bollinger context compact and never invents a different zone timeframe",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("BB 20,2"));
  assert.equal(component.includes("4u zones"),false);
  assert.equal(component.includes("Aster PERP"),false);
});

test("Build 509 makes Bollinger, active-zone shading and day high/low visibly explicit",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(component.includes('rgba(35,190,255,.82)'));
  assert.equal(component.includes('rgba(255,72,111,.78)'),false);
  assert.ok(component.includes('color:"#e4b84a"'));
  assert.ok(component.includes("High vandaag"));
  assert.ok(component.includes("Low vandaag"));
  assert.ok(component.includes('timeZone:"Europe/Amsterdam"'));
  assert.ok(component.includes("const rawLevels=[...resistanceLevels,...supportLevels]"));
  assert.ok(css.includes("portfolio-koers-day-range"));
  assert.ok(css.includes(".portfolio-koers-structure-level.resistance{color:#ff5967}"));
  assert.ok(css.includes(".portfolio-koers-structure-level.support{color:#19dda0}"));
});

test("Portfolio Koers zone overlay renders above the opaque chart canvas",async()=>{
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(css.includes(".portfolio-koers-canvas{position:absolute;inset:0;z-index:2"));
  assert.ok(css.includes(".portfolio-koers-zones{position:absolute;inset:0 48px 0 0;z-index:4"));
});

test("Portfolio Koers UI 4.1 uses straight entry arrows and money-bag TP clusters",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes('multiplier:`${label} ×${count}`'));
  assert.ok(component.includes('glyph:"money"'));
  assert.ok(component.includes('<DirectionArrow direction="up"/>'));
  assert.ok(component.includes('<DirectionArrow direction="down"/>'));
  assert.ok(component.includes("portfolio-koers-event-count"));
  assert.ok(component.includes("connectorStyle(label)"));
  assert.ok(component.includes("openEventCluster(label)"));
  assert.ok(component.includes("/api/exchanges/aster/closed-trades"));
  assert.ok(component.includes("tpTradesForBucketFromActivity"));
  assert.ok(component.includes("<CoinBadge symbol={trade.symbol}/>"));
  assert.ok(component.includes("Totaal gerealiseerd:"));
  assert.ok(component.includes("durationLabel(trade.durationMinutes)"));
  assert.ok(component.includes("ActiveZoneSeatBlock"));
  assert.ok(component.includes('data-reference="file_00000000796c8210aa150351316f20d1"'));
  assert.equal(component.includes("Tik op een TP-marker om de posities te bekijken"),false);
});

test("Portfolio Koers explicitly feeds Bollinger boundaries into marker layout",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("bbUpperByTime"));
  assert.ok(component.includes("bbLowerByTime"));
  assert.ok(component.includes("bandTop:upperY===null?null:Number(upperY)"));
  assert.ok(component.includes("bandBottom:lowerY===null?null:Number(lowerY)"));
});

test("Portfolio Koers follows a newly opened live candle and keeps gappy 15m history read-only",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("scrollToRealTime()"));
  assert.ok(component.includes("portfolioKoersTimelineHealth(canonical.candles,\"15m\",Date.now(),14)"));
  assert.ok(component.includes("nieuwe entries worden geblokkeerd zolang de prijszone-strategie actief is."));
  assert.ok(component.includes("Portfolio Koers blijft informatief"));
  assert.equal(component.includes("applySoldierInstruction"),false);
  assert.equal(component.includes('method:"PUT"'),false);
  assert.equal(component.includes('className="portfolio-koers-gap-warning"'),false);
});

test("Portfolio Koers always opens from the approved 15m default instead of restoring a stale saved timeframe",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.equal(component.includes("tradementor.portfolio-koers.timeframe.v1"),false);
  assert.ok(component.includes('TIMEFRAME_VIEW["15m"]'));
  assert.ok(component.includes("setVisibleLogicalRange"));
  assert.equal(component.includes("fitContent()"),false);
});

test("Portfolio Koers mobile plot reserves only 48px for the price axis and matching overlays",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(component.includes("const PRICE_AXIS_WIDTH=48"));
  assert.ok(component.includes("minimumWidth:PRICE_AXIS_WIDTH"));
  assert.ok(css.includes(".portfolio-koers-event-layer{position:absolute;inset:0 48px 0 0"));
});

test("standard chart event markup contains no event dollar value field",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const layer=component.slice(component.indexOf('className="portfolio-koers-event-layer"'),component.indexOf('{viewMode==="active"&&activeLoading&&!activeCandles.length'));
  assert.equal(layer.includes("label.value"),false);
  assert.equal(layer.includes("compactUsd("),false);
  assert.equal(layer.includes("label.glyph"),false);
  assert.ok(layer.includes("label.multiplier"));
  assert.ok(layer.includes("portfolio-koers-event-chip"));
});

test("Build 432 replaces sword and moneybag clutter with compact clustered chips",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(component.includes("portfolio-koers-event-chip"));
  assert.equal(component.includes('glyph:"⚔"'),false);
  assert.equal(component.includes('glyph:"💰"'),false);
  assert.ok(css.includes(".portfolio-koers-event.portfolio-koers-event-chip"));
});

test("reference-style zone regions remain sourced from confirmed portfolio zones",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("payload.zones.map"));
  assert.ok(component.includes("source:zone.source"));
  assert.ok(component.includes("layoutPortfolioKoersZoneRegions(zoneCoordinates,height)"));
  assert.equal(component.includes("staticZone"),false);
});


test("Build 413 derives live percentage distance and clamped in-zone progress without changing zone prices",()=>{
  const current=144.85,upper=145.27,lower=143.21;
  assert.ok(Math.abs(portfolioZoneDistancePercent(upper,current)-0.2899551259924169)<1e-10);
  assert.ok(Math.abs(portfolioZoneDistancePercent(lower,current)-(-1.1322057300655757))<1e-10);
  assert.ok(Math.abs(portfolioZoneProgress(current,lower,upper)-79.61165048543614)<1e-10);
  assert.equal(portfolioZoneProgress(200,lower,upper),100);
  assert.equal(portfolioZoneProgress(100,lower,upper),0);
});

test("Build 413 initial focus drops old distant history while preserving recent candles around adjacent zones",()=>{
  const old=Array.from({length:24},(_,index)=>({time:index+1,open:100,high:102,low:98,close:100}));
  const recent=Array.from({length:20},(_,index)=>({time:25+index,open:144.1,high:145.1,low:143.6,close:144.8}));
  const rows=[...old,...recent];
  assert.equal(portfolioKoersFocusBars(rows,28,144.85,143.21,145.27),20);
});

test("Build 479 keeps the reference-style longer timeline while visible data drives account autoscale",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  for(const pair of [
    '"1m":{visibleBars:24',
    '"5m":{visibleBars:24',
    '"15m":{visibleBars:23',
    '"1u":{visibleBars:22',
    '"4u":{visibleBars:20',
    '"24u":{visibleBars:18',
  ]) assert.ok(component.includes(pair),pair);
  assert.ok(component.includes("const rawFocusVisibleBars=Math.min(candles.length,view.visibleBars)"));
  assert.ok(component.includes('viewMode==="account"\n      ? portfolioKoersFocusBars(candles,rawFocusVisibleBars'));
  assert.equal(component.includes("guideLow"),false);
  assert.equal(component.includes("guideHigh"),false);
  assert.equal(component.includes("fitContent()"),false);
});


test("Build 414 can stop before a deep old candle after a small recent decision window",()=>{
  const old=Array.from({length:20},(_,index)=>({time:index+1,open:100,high:102,low:98,close:100}));
  const recent=Array.from({length:7},(_,index)=>({time:21+index,open:144.6,high:146.1,low:144.5,close:145.5}));
  assert.equal(portfolioKoersFocusBars([...old,...recent],16,145.53,145.18,146.48),7);
});

test("Build 479 mobile geometry keeps UI 4.1 styling with the requested compact chart height",async()=>{
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(css.includes(".portfolio-zone-map.portfolio-koers-ui41 .portfolio-koers-stage{height:340px}"));
  assert.ok(css.includes(".portfolio-koers-ui41{padding:14px 12px 12px"));
  assert.ok(css.includes("width:min(220px,calc(100% - 56px))"));
  assert.ok(css.includes(".portfolio-koers-ui41-hint"));
  assert.equal(component.includes("voormalige R1 → nieuwe support"),false);
  assert.equal(component.includes(">nieuwe high</div>"),false);
  assert.equal(component.includes(">volgende breakout</div>"),false);
  assert.ok(component.includes("portfolio-koers-tp-detail-leader"));
});

test("Build 474 keeps the reference marker layer calm without deleting underlying events",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("selectPortfolioKoersReferenceCandidates"));
  assert.ok(component.includes("{tp:4,long:4,short:4,cashflow:1,other:1}"));
  assert.ok(component.includes("markerRowsRef.current.filter((row)=>row.time===time)"));
  assert.ok(component.includes("openEventCluster(label)"));
});

test("Build 446 keeps calm price-axis typography without a colored last-value badge",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes('textColor:"#aeb6bb",fontSize:10'));
  assert.ok(component.includes("lastValueVisible:false"));
  assert.ok(component.includes("priceLineVisible:false"));
  assert.ok(component.includes("scaleMargins:{top:.06,bottom:.06}"));
});


test("Build 474 applies reference density only after filtering to the actual visible logical range",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const rangeIndex=component.indexOf("const visibleRange=chart.timeScale().getVisibleLogicalRange()");
  const densityIndex=component.indexOf("selectPortfolioKoersReferenceCandidates(candidates");
  assert.ok(rangeIndex>0);
  assert.ok(component.includes("candleIndex>=Math.floor(visibleRange.from)-1"));
  assert.ok(component.includes("candleIndex<=Math.ceil(visibleRange.to)+1"));
  assert.ok(densityIndex>rangeIndex);
  assert.ok(component.includes("{tp:4,long:4,short:4,cashflow:1,other:1}"));
});

test("Build 422 preserves event-to-candle identity while scrolling and adds no fetch on viewport change",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const syncStart=component.indexOf("const syncOverlays=()=>");
  const syncEnd=component.indexOf("syncOverlaysRef.current=",syncStart);
  const syncBlock=component.slice(syncStart,syncEnd);
  assert.ok(syncBlock.includes("candleIndexByTime"));
  assert.ok(syncBlock.includes("timeToCoordinate(row.time"));
  assert.equal(syncBlock.includes("authenticatedRequest("),false);
  assert.ok(component.includes("subscribeVisibleLogicalRangeChange(rememberViewport)"));
  assert.ok(component.includes("savedViewportRef.current[viewportKey]"));
  assert.ok(component.includes("manualViewportRef.current[viewportKey]"));
});


test("Build 432 cashflow-adjusted performance neutralizes deposits and withdrawals without changing raw equity",()=>{
  const candles=[
    {time:60,atMs:60_000,open:100,high:100,low:100,close:100},
    {time:120,atMs:120_000,open:300,high:300,low:300,close:300},
    {time:180,atMs:180_000,open:195,high:195,low:195,close:195},
  ];
  const markers=[
    {time:120,kind:"cashflow",cashflowType:"DEPOSIT",amountUsd:200},
    {time:180,kind:"cashflow",cashflowType:"WITHDRAWAL",amountUsd:-100},
  ];
  assert.equal(portfolioCashflowShift(markers,60,120),200);
  assert.equal(portfolioCashflowShift(markers,60,180),100);
  const performance=cashflowAdjustedPortfolioSeries(candles,markers);
  assert.deepEqual(performance.map((row)=>row.rawValue),[100,300,195]);
  assert.deepEqual(performance.map((row)=>row.value),[100,100,95]);
});

test("Build 434 opens Portfolio Koers in Accountwaarde while Performance remains an optional tab",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes('useState<PortfolioViewMode>("account")'));
  assert.equal(component.includes('useState<PortfolioViewMode>("performance")'),false);
  assert.ok(component.includes('onClick={()=>setViewMode("performance")}'));
  assert.ok(component.includes('onClick={()=>setViewMode("account")}'));
  assert.ok(component.includes("ACCOUNTWAARDE"));
  assert.ok(component.includes("PERFORMANCE"));
});

test("Build 432 visually separates signed deposits and withdrawals from trading markers",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes('cashflowType==="DEPOSIT"?"Storting"'));
  assert.ok(component.includes('cashflowType==="WITHDRAWAL"?"Opname"'));
  assert.ok(component.includes('copy.tone==="cashflow"?92:copy.tone==="tp"?86:58'));
});


test("Build 435 masks the cached startup chart until the first canonical Accountwaarde load completes",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(component.includes("const [initialChartReady,setInitialChartReady]=useState(false)"));
  assert.ok(component.includes("finally{setLoading(false);setInitialChartReady(true)}"));
  assert.ok(component.includes("!initialChartReady?<div className=\"portfolio-koers-state portfolio-koers-initial-state\""));
  assert.ok(component.includes("loading&&initialChartReady&&!baseCandles.length"));
  assert.ok(css.includes(".portfolio-koers-state.portfolio-koers-initial-state{z-index:12;background:#000}"));
});

test("Build 437 moves Zone-Soldaten status off the chart and into an opaque dedicated screen",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(component.includes("file_00000000c2d0821082a1b3c28f6462c1"));
  assert.ok(component.includes("ZONE_SOLDIERS_OPEN_EVENT"));
  assert.ok(component.includes("ZoneSoldiersCommandCenterScreen"));
  assert.ok(component.includes("document.body"));
  assert.ok(component.includes('document.documentElement.setAttribute("data-zone-soldiers-screen-open","true")'));
  assert.ok(component.includes("SNELLE ACTIES"));
  assert.ok(component.includes("Terug naar snapshot"));
  assert.ok(css.includes(".zsc-screen{position:fixed;z-index:1600;inset:0"));
  assert.ok(component.includes('{false?<section className={`portfolio-strategy-cockpit'));
});


test("Build 550 separates always-visible chart zone from operational trading zone",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.match(component,/runtimeTruth:Record<string,unknown>/);
  assert.match(component,/const runtimeTruth=record\(strategy2\.runtimeTruth\)/);
  assert.match(component,/runtimeTruth\.source==="SERVER_RUNTIME"/);
  assert.match(component,/runtimeTruth\.strategyMode==="ZONE_WARRIORS"/);
  assert.match(component,/const activeZone=liveDisplayActiveZone/);
  assert.match(component,/const operationalActiveZone=runtimeZoneActive\?signedIntegerOrNull\(runtimeTruth\.activeZone\):activeZone/);
  assert.match(component,/onActiveZoneChange\?\.\(activeZone\)/);
  assert.match(component,/runtimeTruth\.zoneSafeForNewEntries===true/);
});

test("Build 521 keeps all touch gestures inside Portfolio Koers while allowing chart vertical pan", async()=>{
  const [component,css]=await Promise.all([
    readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8"),
    readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8"),
  ]);
  assert.ok(component.includes("vertTouchDrag:true"));
  assert.ok(component.includes("horzTouchDrag:true"));
  assert.ok(component.includes("pinch:true"));
  assert.match(css,/\.portfolio-koers-stage\{[^}]*touch-action:none[^}]*overscroll-behavior:none/);
  assert.match(css,/\.portfolio-koers-canvas\{[^}]*touch-action:none!important[^}]*overscroll-behavior:none/);
});


test("Build 549 keeps chart price levels visible when price-zone entries are disabled or refresh temporarily fails",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("lastConfirmedZoneLadderRef"));
  assert.ok(component.includes("const chartZoneLadder=freshChartZoneLadder??lastConfirmedZoneLadderRef.current"));
  assert.ok(component.includes("const activeZone=liveDisplayActiveZone"));
  assert.ok(component.includes("activeZone:operationalActiveZone??activeZone"));
  assert.ok(component.includes("last confirmed 15m zone basis")||component.includes("laatst bevestigde prijsniveaus blijven zichtbaar"));
  const advisorCatch=component.slice(component.indexOf("}catch(reason){",component.indexOf("const loadAdvisor=")),component.indexOf("},[user?.uid])",component.indexOf("const loadAdvisor=")));
  assert.equal(advisorCatch.includes("setAdvisorZones([])"),false);
  assert.equal(advisorCatch.includes("setAdvisorTimeline(null)"),false);
  assert.match(component,/if\(viewMode==="account"&&zoneLadder\?\.zones\?\.length\)/);
  assert.match(component,/portfolio-koers-structure-level/);
});


test("Build 551 restores the Build 512 R1-R4 S1-S4 structure and active-zone band",async()=>{
  const [component,css]=await Promise.all([
    readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8"),
    readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8"),
  ]);
  assert.ok(component.includes('label:"R1"'));
  assert.ok(component.includes('label:`R${offset+1}`'));
  assert.ok(component.includes('label:"S1"'));
  assert.ok(component.includes('label:`S${offset+1}`'));
  assert.ok(component.includes("const rawLevels=[...resistanceLevels,...supportLevels]"));
  assert.ok(component.includes("activeZone:activeTop!==null&&activeBottom!==null"));
  assert.ok(component.includes("label:zoneLabel"));
  assert.doesNotMatch(css,/\.portfolio-koers-ui41 \.portfolio-koers-structure-zone\{\s*display:none!important/);
  assert.doesNotMatch(css,/\.portfolio-koers-ui41 \.portfolio-koers-structure-level>span\{\s*display:none!important/);
  assert.match(css,/\.portfolio-koers-ui41 \.portfolio-koers-structure-level\{right:48px;border-top-width:1px\}/);
});


test("Build 552 keeps confirmed chart zones across cold starts and history gaps",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes('portfolio-chart?timeframe=15m&limit=600'));
  assert.ok(component.includes('tradementor.portfolioZones.v1.'));
  assert.ok(component.includes('const advisorZoneSource=useMemo('));
  assert.ok(component.includes('advisorZones.length?advisorZones:visualPayloadZones'));
  assert.equal(component.includes('advisorTimeline?.safeForAdvisor===true&&advisorZones.length?advisorZones:payload.zones'),false);
  assert.ok(component.includes('manualViewportRef.current[viewportKey]!==true'));
  assert.ok(component.includes('PORTFOLIO_KOERS_DEFAULT_TIMEFRAME'));
  assert.ok(component.includes('const [viewMode,setViewMode]=useState<PortfolioViewMode>("account")'));
});


test("Build 555 keeps next-zone chart context available without backend zones",async()=>{
  const library=await readFile(new URL("../lib/portfolio-koers-chart.mjs",import.meta.url),"utf8");
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.match(library,/export function derivePortfolioDisplayZones/);
  assert.match(library,/browser-confirmed-swings\+sr-cluster\+atr/);
  assert.match(component,/const browserDerivedZones=canonical\.zones\.length/);
  assert.match(component,/const visualPayloadZones=payload\.zones\.length\?payload\.zones:localDisplayZones/);
});


test("Build 559 matches approved Portfolio Koers startup/event reference",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(component.includes("file_0000000065e08246a10dfd2cc721cc77"));
  assert.equal(component.includes('className="portfolio-koers-gap-warning"'),false);
  assert.ok(component.includes('data-level={level.label}'));
  assert.equal(component.includes('<span>{level.label}</span>'),false);
  assert.ok(component.includes('{tp:4,long:4,short:4,cashflow:1,other:1}'));
  assert.ok(component.includes('safetyCap:12'));
  assert.ok(css.includes("Visual reference: file_0000000065e08246a10dfd2cc721cc77"));
  assert.ok(css.includes(".portfolio-koers-gap-warning"));
  assert.ok(css.includes("display:none!important"));
  assert.ok(css.includes(".portfolio-koers-event-chip.long"));
  assert.ok(css.includes(".portfolio-koers-event-chip.short"));
  assert.ok(css.includes(".portfolio-koers-event-chip.tp"));
});


test("Build 560 focuses startup on the live zone and never bridges a history gap with Bollinger",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("latestContiguousPortfolioCandles"));
  assert.ok(component.includes("portfolioKoersFocusBars(candles,rawFocusVisibleBars"));
  assert.ok(component.includes("portfolioZoneContextFromLadder(advisorZoneLadderRef.current,latestPrice)"));
  assert.ok(component.includes("bbSource.length>=20?bollinger20x2(bbSource)"));
  assert.equal(component.includes("const bb=viewMode===\"account\"?bollinger20x2(candles)"),false);
});


test("Build 561 imports the live-zone focus helper used by Portfolio Koers startup",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("portfolioKoersFocusBars"));
  const importLine=component.split("\n").find((line)=>line.includes('from "@/lib/portfolio-koers-chart.mjs"'))||"";
  assert.ok(importLine.includes("portfolioKoersFocusBars"));
});
