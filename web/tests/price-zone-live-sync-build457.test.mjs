import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Build 457 makes Portfolio Koers the single visible live-zone source for Portfolio Snapshot", async () => {
  const [chart, snapshot] = await Promise.all([
    readFile(new URL("../components/portfolio-koers-chart.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(chart, /onActiveZoneChange\?:\(zone:number\|null\)=>void/);
  assert.match(chart, /const liveDisplayActiveZone=zoneContext\?\.activeIndex\?\?confirmedActiveZone/);
  assert.match(chart, /onActiveZoneChange\?\.\(liveDisplayActiveZone\)/);

  assert.match(snapshot, /const \[liveActiveZone, setLiveActiveZone\] = useState<number \| null>\(null\)/);
  assert.match(snapshot, /onActiveZoneChange=\{setLiveActiveZone\}/);
  assert.match(snapshot, /const displayActiveZone = liveActiveZone \?\? summary\.activeZone/);
  assert.match(snapshot, /const seatZoneInSync = liveActiveZone === null \|\| summary\.activeZone === liveActiveZone/);
  assert.match(snapshot, /data-seat-zone-sync=\{seatZoneInSync \? "synced" : "waiting"\}/);
});

test("Build 457 never presents stale active-zone free-seat counts as belonging to the new live zone", async () => {
  const snapshot = await readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8");

  assert.match(snapshot, /Live zone gewijzigd · stoelstatus synchroniseert\./);
  assert.match(snapshot, /seatZoneInSync \? <b><i>\{summary\.freeLongActiveZone\}L<\/i> \/ <em>\{summary\.freeShortActiveZone\}S<\/em><\/b> : <b>— \/ —<\/b>/);
  assert.match(snapshot, /\}, \[host, liveActiveZone\]\);/);
});

test("Build 457 remains a presentation/status-sync fix and adds no trading mutation to Portfolio Koers", async () => {
  const chart = await readFile(new URL("../components/portfolio-koers-chart.tsx", import.meta.url), "utf8");
  assert.equal(chart.includes('method:"POST"'), false);
  assert.equal(chart.includes('method:"PUT"'), false);
  assert.equal(chart.includes("/order"), false);
});
