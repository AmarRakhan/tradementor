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
  assert.match(chart, /const activeZone=liveDisplayActiveZone/);
  assert.match(chart, /const operationalActiveZone=runtimeZoneActive\?signedIntegerOrNull\(runtimeTruth\.activeZone\):activeZone/);
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

test("Build 580 resolves live zone occupancy from canonical server zoneState only", async () => {
  const [snapshot, activeZoneBlock] = await Promise.all([
    readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/active-zone-seat-block.tsx", import.meta.url), "utf8"),
  ]);

  const loaderStart = snapshot.indexOf("async function loadPriceZoneSeatSummary");
  const loaderEnd = snapshot.indexOf("function scannerSideStatus", loaderStart);
  const loader = snapshot.slice(loaderStart, loaderEnd);
  assert.match(loader, /const zoneState = record\(runtimeTruth\.zoneState\)/);
  assert.match(loader, /zoneState\.zones/);
  assert.match(loader, /reconciliationRaw\.strategyMatches/);
  assert.doesNotMatch(loader, /seatModel/);
  assert.doesNotMatch(loader, /multiBbPositions/);
  assert.match(activeZoneBlock, /summary\.zoneOpenCountsReliable/);
  assert.match(snapshot, /seatZoneInSync \? <b><i>\{freeLongActiveZone\}L<\/i> \/ <em>\{freeShortActiveZone\}S<\/em><\/b> : <b>— \/ —<\/b>/);
  assert.match(snapshot, /Live zone gewijzigd · stoelstatus synchroniseert\./);
});

test("Build 457 remains a presentation/status-sync fix and adds no trading mutation to Portfolio Koers", async () => {
  const chart = await readFile(new URL("../components/portfolio-koers-chart.tsx", import.meta.url), "utf8");
  assert.equal(chart.includes('method:"POST"'), false);
  assert.equal(chart.includes('method:"PUT"'), false);
  assert.equal(chart.includes("/order"), false);
});


test("Build 580 removes stale frontend flat/seat reconstruction and accepts zero configured sides", async () => {
  const snapshot = await readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8");
  const loaderStart = snapshot.indexOf("async function loadPriceZoneSeatSummary");
  const loaderEnd = snapshot.indexOf("function scannerSideStatus", loaderStart);
  const loader = snapshot.slice(loaderStart, loaderEnd);
  assert.match(loader, /capacity\.perZoneLong/);
  assert.match(loader, /capacity\.perZoneShort/);
  assert.match(loader, /Math\.max\(0, Math\.round\(optionalNumber\(capacity\.perZoneShort\) \?\? 0\)\)/);
  assert.doesNotMatch(loader, /exchangeFlatConfirmed/);
  assert.doesNotMatch(loader, /seatModel/);
  assert.doesNotMatch(loader, /priceZoneSeats/);
  assert.doesNotMatch(loader, /zoneSoldiers/);
  assert.doesNotMatch(loader, /multiBbPositions/);
});

