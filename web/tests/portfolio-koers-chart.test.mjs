import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { PORTFOLIO_KOERS_DEFAULT_TIMEFRAME, PORTFOLIO_KOERS_TIMEFRAMES, aggregatePortfolioEquityHistory, bollinger20x2, markerVisual, mergePortfolioKoersCandles, mergeRealtimeEquitySample, normalizePortfolioKoersPayload, parsePortfolioEquityText, portfolioKoersFocusBars, portfolioKoersTimelineHealth, portfolioZoneDistancePercent, portfolioZoneForPrice, portfolioZoneProgress } from "../lib/portfolio-koers-chart.mjs";

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
  const snapshotMount=source.indexOf("\n      <Snapshot\n",portalStart);
  assert.ok(portalStart>0);
  assert.ok(chartMount>portalStart);
  assert.ok(snapshotMount>chartMount);
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("Portfolio Koers"));
  assert.ok(component.includes("Totale portfolio waarde (USDT)"));
  assert.ok(component.includes("{timeframe} candles · {timeframe} zones · BB 20,2"));
  assert.ok(component.includes("priceToCoordinate(zone.center)"));
  assert.ok(component.includes("priceToCoordinate(zone.upper)"));
  assert.ok(component.includes("priceToCoordinate(zone.lower)"));
  assert.ok(component.includes("layoutPortfolioKoersZoneRegions"));
  assert.ok(component.includes("layoutPortfolioKoersMarkers"));
  assert.ok(component.includes("maxFull:3"));
  assert.ok(component.includes("maxCompact:2"));
  assert.ok(component.includes("PRICE_AXIS_WIDTH=48"));
  assert.ok(component.includes("attributionLogo:false"));
  assert.equal(/authenticatedRequest\([^)]*method:\s*["']POST/.test(component),false);
});


test("Portfolio Koers timeframe context never invents a different zone timeframe",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("{timeframe} candles · {timeframe} zones · BB 20,2"));
  assert.equal(component.includes("4u zones"),false);
});

test("Portfolio Koers zone overlay renders above the opaque chart canvas",async()=>{
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(css.includes(".portfolio-koers-canvas{position:absolute;inset:0;z-index:2"));
  assert.ok(css.includes(".portfolio-koers-zones{position:absolute;inset:0 48px 0 0;z-index:4"));
});

test("Portfolio Koers uses icon-only standard events and keeps detail values in the tooltip",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.equal(component.includes("Entry L"),false);
  assert.equal(component.includes("Entry S"),false);
  assert.ok(component.includes('glyph:"⚔"'));
  assert.ok(component.includes('glyph:"💰"'));
  assert.ok(component.includes('value:""'));
  assert.ok(component.includes("markerDetail(row)"));
  assert.ok(component.includes("payload.markers.filter((row)=>row.time===time)"));
});

test("Portfolio Koers explicitly feeds Bollinger boundaries into marker layout",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("bbUpperByTime"));
  assert.ok(component.includes("bbLowerByTime"));
  assert.ok(component.includes("bandTop:upperY===null?null:Number(upperY)"));
  assert.ok(component.includes("bandBottom:lowerY===null?null:Number(lowerY)"));
});

test("Portfolio Koers follows a newly opened live candle and fails closed before changing soldiers on gappy 15m history",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("scrollToRealTime()"));
  assert.ok(component.includes("portfolioKoersTimelineHealth(canonical.candles,\"15m\",Date.now(),14)"));
  assert.ok(component.includes("Soldaten worden niet aangepast zolang de 15m-zonebasis niet aaneengesloten is."));
  assert.ok(component.includes("portfolio-koers-gap-warning"));
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
  const layer=component.slice(component.indexOf('className="portfolio-koers-event-layer"'),component.indexOf("{loading&&!baseCandles.length"));
  assert.equal(layer.includes("label.value"),false);
  assert.equal(layer.includes("compactUsd("),false);
  assert.ok(layer.includes("label.glyph"));
  assert.ok(layer.includes("label.multiplier"));
});

test("Portfolio Koers build 401 follows the approved sword-marker reference",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  const css=await readFile(new URL("../app/portfolio-koers-chart.css",import.meta.url),"utf8");
  assert.ok(component.includes('data-reference="file_00000000dd24820eaa6e54ec1054904f"'));
  assert.ok(component.includes('glyph:"⚔"'));
  assert.ok(component.includes('glyph:"💰"'));
  assert.ok(css.includes(".portfolio-koers-event-icon"));
  assert.ok(css.includes(".portfolio-koers-event-badge"));
  assert.ok(css.includes(".portfolio-koers-connector"));
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

test("Build 413 configures every approved timeframe for a closer initial viewport and keeps timeframe switching focused",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  for(const pair of [
    '"1m":{visibleBars:24',
    '"5m":{visibleBars:20',
    '"15m":{visibleBars:16',
    '"1u":{visibleBars:16',
    '"4u":{visibleBars:14',
    '"24u":{visibleBars:12',
  ]) assert.ok(component.includes(pair),pair);
  assert.ok(component.includes("portfolioKoersFocusBars(candles,view.visibleBars"));
  assert.ok(component.includes("focusVisibleBars"));
  assert.ok(component.includes("guideLow"));
  assert.ok(component.includes("guideHigh"));
  assert.equal(component.includes("fitContent()"),false);
});


test("Build 414 can stop before a deep old candle after a small recent decision window",()=>{
  const old=Array.from({length:20},(_,index)=>({time:index+1,open:100,high:102,low:98,close:100}));
  const recent=Array.from({length:7},(_,index)=>({time:21+index,open:144.4,high:146.1,low:143.8,close:145.5}));
  assert.equal(portfolioKoersFocusBars([...old,...recent],16,145.53,145.18,146.48),7);
});

test("Build 414 reduces price-axis typography while keeping live equity as the last-value label",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes('textColor:"#9fb0ba",fontSize:10'));
  assert.ok(component.includes("lastValueVisible:true"));
  assert.ok(component.includes("scaleMargins:{top:.12,bottom:.12}"));
});
