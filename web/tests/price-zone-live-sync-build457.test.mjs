import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Runtime Contract V1 keeps Portfolio Koers and Portfolio Snapshot on one operational active-zone source", async () => {
  const [chart, snapshot, activeZoneBlock] = await Promise.all([
    readFile(new URL("../components/portfolio-koers-chart.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/active-zone-seat-block.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(chart, /onActiveZoneChange\?:\(zone:number\|null\)=>void/);
  assert.match(chart, /const liveDisplayActiveZone=zoneContext\?\.activeIndex\?\?confirmedActiveZone/);
  assert.match(chart, /const activeZone=runtimeZoneActive\?signedIntegerOrNull\(runtimeTruth\.activeZone\):liveDisplayActiveZone/);
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
