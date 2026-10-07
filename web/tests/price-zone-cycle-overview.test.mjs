import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const overview = fs.readFileSync(new URL("../components/price-zone-cycle-overview.tsx", import.meta.url), "utf8");
const snapshot = fs.readFileSync(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8");
const css = fs.readFileSync(new URL("../app/portfolio-snapshot.css", import.meta.url), "utf8");

test("Build 570 mounts the approved current-cycle zone overview directly below Pricezone-strategie", () => {
  assert.match(snapshot, /<PriceZoneStrategySummary[\s\S]*<PriceZoneCycleOverview/);
  assert.match(overview, /file_00000000941881f48d08a2c072cf8ad7/);
  assert.match(overview, /Zone overzicht/);
  assert.match(overview, /huidige cyclus/);
});

test("zone overview is read-only and consumes canonical Aster, Portfolio Koers and confirmed-event feeds", () => {
  assert.match(overview, /authenticatedRequest\("\/api\/exchanges\/aster"/);
  assert.match(overview, /portfolio-chart\?timeframe=15m&limit=600/);
  assert.match(overview, /portfolio-chart\/events\?timeframe=15m/);
  assert.doesNotMatch(overview, /method:\s*["']POST["']/);
  assert.doesNotMatch(overview, /strategy2\/(start|stop|settings|tick)/);
});

test("zone overview preserves data-truth semantics and origin-zone ownership", () => {
  assert.match(overview, /zoneOpenCountsReliable/);
  assert.match(overview, /originZone/);
  assert.match(overview, /openKeys\.size !== strategyOpenTotal/);
  assert.match(overview, /Onbekende waarden blijven daarom bewust op —/);
  assert.match(overview, /event\.activityType === "PARTIAL_TP"/);
});

test("approved mobile visual contract keeps internal table scroll and sticky Zone column", () => {
  assert.match(css, /Build 570 · Prijszone Details — huidige cyclus/);
  assert.match(css, /file_00000000941881f48d08a2c072cf8ad7/);
  assert.match(css, /\.aps-zco-table-wrap\{[^}]*overflow-x:auto/);
  assert.match(css, /\.aps-zco-table th:first-child,.aps-zco-table td:first-child\{[^}]*position:sticky;left:0/);
  assert.match(css, /\.aps-zco-table tr\.is-active td\{[^}]*#e7b836/);
});
