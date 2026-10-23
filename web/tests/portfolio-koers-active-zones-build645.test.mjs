import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const read=(path)=>readFile(new URL(path,import.meta.url),"utf8");

test("Build 645 Actieve Trades loads the LONG-basket zone index through the cloud proxy",async()=>{
  const route=await read("../app/api/exchanges/aster/portfolio-chart/active-zones/route.ts");
  assert.ok(route.includes('proxyCloud(request, "/v1/me/aster/portfolio-chart/active-zones", "GET")'));
  const source=await read("../components/portfolio-koers-chart.tsx");
  assert.ok(source.includes("/api/exchanges/aster/portfolio-chart/active-zones?timeframe="));
  assert.ok(source.includes("const activeCandles=zonesIndexReady?activeZones.candles:activePayload.candles;"));
});

test("Build 645 zones are drawn only on the Actieve Trades view, never on Accountwaarde",async()=>{
  const source=await read("../components/portfolio-koers-chart.tsx");
  assert.ok(source.includes('{viewMode==="active"?<div className="portfolio-koers-sr-layer"'));
  assert.ok(source.includes('if(viewMode==="active"&&activeZonesRef.current.candles.length>=20){'));
  assert.ok(source.includes("setActiveZoneOverlay(EMPTY_ACTIVE_ZONE_OVERLAY);"));
});

test("Build 645 levels show kind, touches and role flip; strength drives emphasis",async()=>{
  const source=await read("../components/portfolio-koers-chart.tsx");
  assert.ok(source.includes('const tag=`${level.kind==="support"?"S":"R"}${level.flipped?" ↺":""} · ${level.touches}×`;'));
  const css=await read("../app/portfolio-koers-chart.css");
  for(const rule of [".portfolio-koers-sr-level.support{color:#2be4a7}",".portfolio-koers-sr-level.resistance{color:#ff6274}",".portfolio-koers-sr-level.flipped{border-top-style:solid}",".portfolio-koers-sr-layer{position:absolute;inset:0 48px 0 0;z-index:5;overflow:hidden;pointer-events:none"]) assert.ok(css.includes(rule),rule);
});
