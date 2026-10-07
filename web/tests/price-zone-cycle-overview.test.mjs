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

test("zone overview reuses the canonical Aster seat snapshot and only polls chart/event read feeds itself", () => {
  assert.match(snapshot, /authenticatedRequest\("\/api\/exchanges\/aster"/);
  assert.match(snapshot, /openZonePositionKeys/);
  assert.doesNotMatch(overview, /authenticatedRequest\("\/api\/exchanges\/aster"\s*,/);
  assert.match(overview, /portfolio-chart\?timeframe=15m&limit=320/);
  assert.match(overview, /portfolio-chart\/events\?timeframe=15m/);
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


test("Build 572 cannot remain indefinitely on the zone loading state", () => {
  assert.match(overview, /Promise\.allSettled/);
  assert.match(overview, /window\.setTimeout\(\(\) => controller\.abort\(\), 8000\)/);
  assert.match(overview, /if \(!seatTruth\) return null/);
  assert.doesNotMatch(overview, /setSeatTruth\(/);
  assert.match(overview, /Geen betrouwbare zonegegevens beschikbaar/);
});


test("Build 577 keeps configured zero SHORT capacity and fills visible zone ranges from the canonical ladder", () => {
  assert.match(snapshot, /Math\.max\(0, Math\.round\(firstNumber\(\[settings\], \["zoneBaseShortSoldiers", "perZoneShort"\]\) \?\? 0\)\)/);
  assert.doesNotMatch(snapshot, /firstNumber\(\[settings, seatModel\], \["zoneBaseShortSoldiers", "perZoneShort"\]\)/);
  assert.match(overview, /derivePortfolioZoneLadder/);
  assert.match(overview, /minIndex: minVisibleZone/);
  assert.match(overview, /maxIndex: maxVisibleZone/);
});
