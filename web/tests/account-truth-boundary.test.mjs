import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { normalizeAsterAccountTruth } from "../lib/aster-account-truth.ts";
import { withBoundedRetry } from "../lib/bounded-retry.mjs";

test("canonical Aster account truth is strict and fail-closed",()=>{
  const payload={accountTruth:{
    schemaVersion:1,contract:"ASTER_ACCOUNT_TRUTH_V1",source:"ASTER_SERVER_CANONICAL_STATUS",
    capturedAtMs:123,stale:false,configured:true,readOnly:true,ordersSent:0,
    account:{equity:321.45,availableBalance:200,activeTradeCapital:121.45,liquidationRiskPct:12.5},
    positions:{count:2,longCount:1,shortCount:1,rows:[]},
    performance:{dayHigh:330,dayLow:315,realizedPnlToday:4.2,tradesClosedToday:3,closedTodayReliable:true,todayGrowthPercentage:1.2,averageDailyGrowthPercentage:.8,growthReliable:true},
    strategy:{settings:{longSlots:2,shortSlots:1},runtimeTruth:{source:"SERVER_RUNTIME"},summary:{enabled:true,monitor:false,activeLong:1,activeShort:1,longCapacity:2,shortCapacity:1,dcaCount:4,phase:"RUNNING"}},
    provenance:{},
  }};
  const truth=normalizeAsterAccountTruth(payload);
  assert.equal(truth.account.equity,321.45);
  assert.equal(truth.performance.dayHigh,330);
  assert.equal(truth.performance.dayLow,315);
  assert.equal(truth.strategy.summary.dcaCount,4);
  assert.throws(()=>normalizeAsterAccountTruth({accountTruth:{schemaVersion:1,contract:"ASTER_ACCOUNT_TRUTH_V1",readOnly:false,ordersSent:0}}));
});

test("bounded retry remains independent from any account cache",async()=>{
  let calls=0;
  const value=await withBoundedRetry(async()=>{
    calls+=1;
    if(calls===1)throw new Error("temporary");
    return "ok";
  },{attempts:2,delays:[0]});
  assert.equal(value,"ok");
  assert.equal(calls,2);
});

test("build 571 forbids browser-owned Aster business truth",async()=>{
  const [exchangeData,chart,snapshot,realtime,auth]=await Promise.all([
    readFile(new URL("../lib/use-exchange-data.ts",import.meta.url),"utf8"),
    readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8"),
    readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx",import.meta.url),"utf8"),
    readFile(new URL("../lib/aster-realtime.mjs",import.meta.url),"utf8"),
    readFile(new URL("../components/auth-provider.tsx",import.meta.url),"utf8"),
  ]);
  for(const forbidden of ["loadAsterSnapshot","saveAsterSnapshot","mergeAsterSnapshotWithHistoryFallback","preserveConfirmedAsterValues"]){
    assert.equal(exchangeData.includes(forbidden),false,forbidden);
  }
  assert.equal(exchangeData.includes('timedRead("/api/exchanges/aster/closed-trades")'),false);
  assert.equal(exchangeData.includes("window.localStorage"),false);
  assert.equal(chart.includes("window.localStorage"),false);
  assert.equal(chart.includes("tradementor.portfolioEquity"),false);
  assert.equal(chart.includes("derivePortfolioDisplayZones"),false);
  assert.equal(chart.includes("mergeRealtimeEquitySample"),false);
  assert.equal(snapshot.includes('metric("PORTFOLIOWAARDE")'),false);
  assert.equal(snapshot.includes('querySelector<HTMLElement>(".portfolio-growth-daily")'),false);
  assert.match(snapshot,/normalizeAsterAccountTruth/);
  assert.equal(realtime.includes("realtimeEquity"),false);
  assert.equal(realtime.includes("unrealizedPnl: totalPnl"),false);
  assert.match(realtime,/Never recompute notional, PnL or equity in the browser/);
  assert.match(auth,/One-way cleanup of retired browser business-truth caches/);
});

test("Portfolio Koers daily high/low is server-owned",async()=>{
  const [chart,library]=await Promise.all([
    readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8"),
    readFile(new URL("../lib/portfolio-koers-chart.mjs",import.meta.url),"utf8"),
  ]);
  assert.match(library,/dayHigh:finite\(source\.dayHigh\) \|\| null/);
  assert.match(library,/dayLow:finite\(source\.dayLow\) \|\| null/);
  assert.match(chart,/payload\.dayHigh/);
  assert.match(chart,/payload\.dayLow/);
  assert.equal(chart.includes("amsterdamDayKey(Date.now())"),false);
});
