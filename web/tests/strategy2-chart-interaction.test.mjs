import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../app/strategy2-reference.css", import.meta.url), "utf8");
const chart = readFileSync(new URL("../components/trading-chart.tsx", import.meta.url), "utf8");

test("Strategy 2 chart stays draggable without stealing normal page scroll", () => {
  assert.match(css, /\.aster-detail-chart \.chart-canvas\s*\{[\s\S]*touch-action:\s*pan-y\s*!important;[\s\S]*pointer-events:\s*auto\s*!important;/i);
  assert.match(css, /\.aster-detail-chart \.chart-canvas canvas\s*\{[\s\S]*touch-action:\s*pan-y\s*!important;[\s\S]*pointer-events:\s*auto\s*!important;/i);
  assert.doesNotMatch(css, /\.aster-detail-chart \.chart-canvas[^}]*pointer-events:\s*none/i);
  assert.match(chart, /horzTouchDrag:true/);
  assert.match(chart, /axisPressedMouseMove:true/);
});

test("Strategy 2 right price scale remains touch draggable", () => {
  assert.match(css, /\.aster-detail-chart \.chart-canvas table tr:first-child > td:last-child,[\s\S]*touch-action:\s*none\s*!important;/i);
  assert.match(css, /\.aster-detail-chart \.chart-canvas table tr:first-child > td:last-child canvas[\s\S]*pointer-events:\s*auto\s*!important;/i);
});
