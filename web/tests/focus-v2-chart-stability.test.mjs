import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const chart = readFileSync(new URL("../components/trading-chart.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../app/aster-tables.css", import.meta.url), "utf8");

test("Focus labels stay left of a clean reserved price-axis gutter", () => {
  assert.match(css, /\.focus-level-overlay\{[^}]*pointer-events:none/);
  assert.match(css, /\.focus-level-segment\{[^}]*right:82px[^}]*pointer-events:none/);
  assert.match(chart, /rightPriceScale:\{[^}]*minimumWidth:72/);
  assert.doesNotMatch(css, /\.focus-level-segment\{[^}]*left:74%/);
});

test("live cockpit data updates segments without becoming a chart rebuild dependency", () => {
  assert.match(chart, /focusSegmentRefs\.current\[key\]/);
  assert.match(chart, /setSegment\("be",cockpit\?\.longBreakEvenPrice\)/);
  assert.match(chart, /setSegment\("dca",cockpit\?\.nextLongDcaPrice\)/);
  assert.match(chart, /setSegment\("tp",focusTakeProfitPrice\)/);
  assert.match(chart, /addSegment\("tp","#b978ff",2\)/);
  assert.match(chart, /setSegment\("release",cockpit\?\.hedgeReleasePrice/);
  const rebuild = chart.match(/\},\[datasetVersion[^\]]+\]\);/)?.[0] || "";
  assert.ok(rebuild, "chart rebuild dependency list exists");
  assert.doesNotMatch(rebuild, /cockpit/);
  assert.match(rebuild, /tradeEventsSignature/);
  assert.doesNotMatch(rebuild, /,tradeEvents,/);
  assert.match(rebuild, /dcaLevelsSignature/);
  assert.match(rebuild, /airbagEventsSignature/);
});
