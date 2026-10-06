import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Build 550 keeps Portfolio Koers visual zone synced to Snapshot while runtime truth governs seat occupancy", async () => {
  const [chart, snapshot, activeZoneBlock] = await Promise.all([
    readFile(new URL("../components/portfolio-koers-chart.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/active-zone-seat-block.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(chart, /onActiveZoneChange\?:\(zone:number\|null\)=>void/);
  assert.match(chart, /const liveDisplayActiveZone=zoneContext\?\.activeIndex\?\?confirmedActiveZone/);
  assert.match(chart, /const activeZone=liveDisplayActiveZone/);\n  assert.match(chart, /const operationalActiveZone=runtimeZoneActive\?signedIntegerOrNull\(runtimeTruth\.activeZone\):activeZone/);
  assert.match(chart, /onActiveZoneChange\?\.\(activeZone\)/);

  assert.match(snapshot, /const \[liveActiveZone, setLiveActiveZone\] = useState<number \| null>\(null\)/);
  assert.match(snapshot, /onActiveZoneChange=\{setLiveActiveZone\}/);
  assert.match(activeZoneBlock, /const displayActiveZone = summary\.runtimeTruthCanonical[\s\S]*\? summary\.activeZone[\s\S]*: \(liveActiveZone \?\? summary\.activeZone\)/);
  assert.match(activeZoneBlock, /const backendZoneMatches =[\s\S]*displayActiveZone !== null && summary\.activeZone === displayActiveZone/);
  assert.match(activeZoneBlock, /const seatZoneInSync = resolvedCounts !== null/);
  assert.match(activeZoneBlock, /summary\.zoneOpenCountsReliable/);
  assert.match(snapshot, /activeZoneSeatSummary=\{priceZoneSeats\}/);
  assert.match(snapshot, /activeZoneSeatLiveZone=\{liveActiveZone\}/);
  assert.match(chart, /<ActiveZoneSeatBlock summary=\{activeZoneSeatSummary \?\? null\} liveActiveZone=\{activeZoneSeatLiveZone \?\? null\} \/>/);
  assert.match(snapshot, /data-seat-zone-sync=\{seatZoneInSync \? "synced" : "waiting"\}/);
});

test("Build 469 resolves the new live zone from a complete verified per-zone breakdown and never relabels stale counts", async () => {
  const [snapshot, activeZoneBlock] = await Promise.all([
    readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/active-zone-seat-block.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(activeZoneBlock, /const breakdown =[\s\S]*displayActiveZone === null[\s\S]*summary\.zoneOpenCounts\[String\(displayActiveZone\)\] \|\| null/);
  assert.match(activeZoneBlock, /displayActiveZone !== null && summary\.zoneOpenCountsReliable/);
  assert.match(activeZoneBlock, /breakdown\?\.long \?\? 0/);
  assert.match(activeZoneBlock, /breakdown\?\.short \?\? 0/);
  assert.match(snapshot, /totals\.long === strategyOpenLong/);
  assert.match(snapshot, /totals\.short === strategyOpenShort/);
  assert.match(snapshot, /derivedTotals\.long === strategyOpenLong/);
  assert.match(snapshot, /derivedTotals\.short === strategyOpenShort/);
  assert.match(snapshot, /seatZoneInSync \? <b><i>\{freeLongActiveZone\}L<\/i> \/ <em>\{freeShortActiveZone\}S<\/em><\/b> : <b>— \/ —<\/b>/);
  assert.match(snapshot, /Live zone gewijzigd · stoelstatus synchroniseert\./);
  assert.match(snapshot, /\}, \[host, liveActiveZone\]\);/);
});

test("Build 457 remains a presentation/status-sync fix and adds no trading mutation to Portfolio Koers", async () => {
  const chart = await readFile(new URL("../components/portfolio-koers-chart.tsx", import.meta.url), "utf8");
  assert.equal(chart.includes('method:"POST"'), false);
  assert.equal(chart.includes('method:"PUT"'), false);
  assert.equal(chart.includes("/order"), false);
});


test("Build 530 makes zero-position exchange truth override stale Zone Warriors seat ownership", async () => {
  const snapshot = await readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8");
  assert.match(snapshot, /const exchangeFlatConfirmed = hasRuntimeTruth[\s\S]*runtimeActiveLong === 0 && runtimeActiveShort === 0 && runtimeAccountPositionCount === 0[\s\S]*reportActiveLong === 0 && reportActiveShort === 0/);
  assert.match(snapshot, /firstNumber\(\[settings, seatModel\], \["zoneBaseLongSoldiers", "perZoneLong"\]\)/);
  assert.match(snapshot, /firstNumber\(\[settings, seatModel\], \["zoneBaseShortSoldiers", "perZoneShort"\]\)/);
  assert.match(snapshot, /const activeOpenLong = exchangeFlatConfirmed \? 0/);
  assert.match(snapshot, /const strategyOpenLong = exchangeFlatConfirmed \? 0/);
  assert.match(snapshot, /exchangeFlatConfirmed \? \{\} : record\(seatReport\.zoneOpenCounts\)/);
  assert.match(snapshot, /if \(!exchangeFlatConfirmed && !zoneOpenCountsReliable\)/);
  assert.match(snapshot, /openFromOldZones: exchangeFlatConfirmed \? 0/);
  assert.match(snapshot, /strategyOpenTotal: exchangeFlatConfirmed \? 0/);
});
