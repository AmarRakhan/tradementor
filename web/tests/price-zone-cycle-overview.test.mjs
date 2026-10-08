import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const overview = fs.readFileSync(new URL("../components/price-zone-cycle-overview.tsx", import.meta.url), "utf8");
const snapshot = fs.readFileSync(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8");
const css = fs.readFileSync(new URL("../app/portfolio-snapshot.css", import.meta.url), "utf8");

test("zone overview mounts directly below Prijszone-strategie", () => {
  assert.match(snapshot, /<PriceZoneStrategySummary[\s\S]*<PriceZoneCycleOverview/);
  assert.match(overview, /file_00000000773c8210ad977be9527738e6/);
  assert.match(overview, /Zone overzicht/);
  assert.match(overview, /huidige cyclus/);
});

test("zone overview consumes canonical zoneState and only polls the read-only cycle event feed", () => {
  assert.match(snapshot, /const zoneState = record\(runtimeTruth\.zoneState\)/);
  assert.match(snapshot, /zoneState\.source !== "SERVER_RUNTIME"/);
  assert.match(snapshot, /openZonePositionKeys/);
  assert.doesNotMatch(overview, /portfolio-chart\?timeframe=15m/);
  assert.match(overview, /portfolio-chart\/events\?timeframe=15m/);
  assert.doesNotMatch(overview, /derivePortfolioZoneLadder/);
  assert.doesNotMatch(overview, /method:\s*["']POST["']/);
  assert.doesNotMatch(overview, /strategy2\/(start|stop|settings|tick)/);
});

test("zone overview preserves data-truth semantics and origin-zone ownership", () => {
  assert.match(overview, /zoneOpenCountsReliable/);
  assert.match(overview, /originZone/);
  assert.match(overview, /seats\.openKeys\.size === seats\.strategyOpenTotal/);
  assert.match(overview, /Onbekende waarden blijven daarom bewust op —/);
  assert.match(overview, /trade\.activityType === "PARTIAL_TP"/);
});

test("Build 574 keeps the zone overview to five columns without horizontal scrolling", () => {
  assert.match(overview, /file_00000000773c8210ad977be9527738e6/);
  assert.match(overview, /Prijsrange/);
  assert.match(overview, /Totaal<small>bezet<\/small>/);
  assert.doesNotMatch(overview, /<th>Status<\/th>/);
  assert.doesNotMatch(overview, /<th>Vrij<\/th>/);
  assert.doesNotMatch(overview, /<th>Profits/);
  assert.match(overview, /colSpan=\{5\}/);
  assert.match(css, /Build 574 · Prijszone Details — compact vijfkoloms zoneoverzicht/);
  assert.match(css, /file_00000000773c8210ad977be9527738e6/);
  assert.match(css, /\.aps-zco-table-wrap\{[^}]*overflow-x:hidden/);
  assert.match(css, /\.aps-zco-table\{[^}]*min-width:0;table-layout:fixed/);
  assert.doesNotMatch(css, /\.aps-zco-table-wrap\{[^}]*overflow-x:auto/);
  assert.match(css, /\.aps-zco-table tr\.is-active td\{[^}]*#e7b836/);
});


test("cycle-event refresh cannot block canonical zone-table rendering", () => {
  assert.match(overview, /window\.setTimeout\(\(\) => controller\.abort\(\), 8000\)/);
  assert.match(overview, /aria-busy=\{false\}/);
  assert.doesNotMatch(overview, /Promise\.allSettled/);
  assert.doesNotMatch(overview, /setSeatTruth\(/);
});


test("Build 580 forbids frontend zone-count/capacity reconstruction", () => {
  const start = snapshot.indexOf("async function loadPriceZoneSeatSummary");
  const end = snapshot.indexOf("function scannerSideStatus", start);
  const loader = snapshot.slice(start, end);
  assert.match(loader, /record\(runtimeTruth\.zoneState\)/);
  assert.match(loader, /capacity\.perZoneShort/);
  assert.match(loader, /zoneState\.zones/);
  assert.doesNotMatch(loader, /seatModel/);
  assert.doesNotMatch(loader, /priceZoneSeats/);
  assert.doesNotMatch(loader, /zoneSoldiers/);
  assert.doesNotMatch(loader, /multiBbPositions/);
  assert.match(overview, /seatSummary\?\.zones/);
  assert.match(overview, /seatSummary\.reconciliation\.otherOpenTotal/);
  assert.match(overview, /otherOpenPositions\.map/);
});

test("Build 581 shows only canonical positive price ranges and server-owned LONG targets", () => {
  assert.match(overview, /const validZoneRange/);
  assert.match(overview, /zone\.lower > 0 && zone\.upper > zone\.lower/);
  assert.match(overview, /Canonical prijsgrenzen ontbreken/);
  assert.doesNotMatch(overview, /zone\.lower \?\? zone\.center/);
  assert.doesNotMatch(overview, /zone\.upper \?\? zone\.center/);
  assert.match(snapshot, /record\(zoneState\.nextLongLevels\)/);
  assert.match(overview, /seatSummary\.nextLongLevels\[direction\]/);
  assert.match(overview, /Volgende vrije LONG-capaciteit/);
  assert.doesNotMatch(overview, /setInterval\(.*nextLongLevels/);
});

test("Build 582 renders server-owned remaining LONG distances in compact header", () => {
  assert.match(overview, /aps-zco-compact-summary/);
  assert.match(overview, /level\?\.distance/);
  assert.match(overview, /↑ Omhoog/);
  assert.match(overview, /↓ Omlaag/);
  assert.doesNotMatch(overview, /aps-zco-next-levels/);
});


test("Build 583 shows all canonical zone rows in vertically scrollable table", () => {
  assert.match(overview, /overflowY: "auto"/);
  assert.match(overview, /maxHeight: "min\(58vh, 640px\)"/);
  assert.match(overview, /position: "sticky"/);
  assert.doesNotMatch(overview, /\.slice\(0, 25\)/);
});


test("Build 584 limits the scroll list to occupied zones plus five on both sides", () => {
  assert.match(overview, /\.filter\(\(\[, count\]\) => count\.total > 0\)/);
  assert.match(overview, /Math\.min\(\.\.\.middle\) - 5/);
  assert.match(overview, /Math\.max\(\.\.\.middle\) \+ 5/);
  assert.match(overview, /zone >= minimum && zone <= maximum/);
});
