import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { PORTFOLIO_KOERS_DEFAULT_TIMEFRAME, PORTFOLIO_KOERS_TIMEFRAMES, bollinger20x2, markerVisual, mergeRealtimeEquitySample, normalizePortfolioKoersPayload, parsePortfolioEquityText, portfolioZoneForPrice } from "../lib/portfolio-koers-chart.mjs";

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

test("Realtime portfolio samples use only the observed equity value for a new candle",()=>{
  const next=mergeRealtimeEquitySample([{time:60,open:100,high:100,low:99,close:99,atMs:60_000}],105,301_000,"5m");
  assert.equal(next.length,2);
  assert.deepEqual({open:next[1].open,high:next[1].high,low:next[1].low,close:next[1].close},{open:105,high:105,low:105,close:105});
});

test("Locale portfolio equity text is parsed without changing its value",()=>{
  assert.equal(parsePortfolioEquityText("US$ 1.234,56"),1234.56);
  assert.equal(parsePortfolioEquityText("$276.42"),276.42);
  assert.equal(parsePortfolioEquityText("—"),null);
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

test("Portfolio Koers is mounted before the existing Portfolio Snapshot and remains read-only",async()=>{
  const source=await readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx",import.meta.url),"utf8");
  assert.ok(source.indexOf("<PortfolioKoersChart")>0);
  assert.ok(source.indexOf("<PortfolioKoersChart")<source.indexOf("<Snapshot"));
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("Bollinger 20,2"));
  assert.ok(component.includes("Transfers apart"));
  assert.equal(/authenticatedRequest\([^)]*method:\s*["']POST/.test(component),false);
});
