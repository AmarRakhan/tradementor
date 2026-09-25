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

test("Portfolio Koers uses a lightweight five-second marker feed without rebuilding the chart",async()=>{
  const [component,route]=await Promise.all([
    readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8"),
    readFile(new URL("../app/api/exchanges/aster/portfolio-chart/events/route.ts",import.meta.url),"utf8"),
  ]);
  assert.ok(component.includes("/api/exchanges/aster/portfolio-chart/events?timeframe="));
  assert.ok(component.includes("},5_000);"));
  assert.ok(component.includes("const markerRowsRef=useRef<Marker[]>([])"));
  assert.ok(component.includes("markerRowsRef.current.filter((row)=>candleByTime.has(row.time))"));
  assert.ok(component.includes("setHover({candle,markers:markerRowsRef.current.filter((row)=>row.time===time)})"));
  assert.ok(component.includes("},[baseCandles,payload.zones,payload.cycleStartEquity,timeframe,viewMode,cashflowSignature]);"));
  assert.equal(component.includes("},[baseCandles,payload.markers,payload.zones,payload.cycleStartEquity,timeframe,viewMode,cashflowSignature]);"),false);
  assert.ok(component.includes("const cashflowSignature=useMemo"));
  assert.ok(route.includes("/v1/me/aster/portfolio-chart/events"));
});
