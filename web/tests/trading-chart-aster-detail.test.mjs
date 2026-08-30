import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const chart = readFileSync(new URL("../components/trading-chart.tsx", import.meta.url), "utf8");
const recent = readFileSync(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");

test("Aster detail chart uses break-even and remaining DCA overlays", () => {
  assert.match(chart, /title:\s*"WINST VANAF"/);
  assert.match(chart, /VOLGENDE \$\{selection\.side\.toUpperCase\(\)\} DCA/);
  assert.match(chart, /title:next\?.*:`DCA \$\{Math\.round\(Number\(level\.number\)\)\}`/s);
  assert.match(chart, /breakEvenPrice/);
  assert.match(chart, /dcaLevels/);
  assert.doesNotMatch(chart, /group\.events\[0\]\?\.kind==="dca"\?"ADD"/);
  assert.doesNotMatch(chart, /entrySeries\.setData/);
});

test("open detail is refreshed from live Strategy 2 position state", () => {
  assert.match(recent, /strategy2Tp\?\.breakEvenPrice/);
  assert.match(recent, /strategy2DcaLadder\?\.levels/);
  assert.match(recent, /breakEvenPrice=\{detailBreakEvenPrice\}/);
  assert.match(recent, /dcaLevels=\{detailDcaLevels\}/);
});


test("Aster Focus 2.0 detail shows the confirmed protective hedge separately", () => {
  assert.match(chart, /useState\(mode === "aster-detail" \? "1m" : "15m"\)/);
  assert.match(chart, /FOCUS_V2_LONG/);
  assert.match(chart, /hedgeQuery/);
  assert.match(chart, /kind:"hedge" as const/);
  assert.match(chart, /SHORT RELEASE/);
  assert.match(chart, /HEDGE/);
});

test("Focus 2.0 does not duplicate legacy detail overlays", () => {
  assert.match(chart, /if \(mode === "aster-detail" && !focusV2\)/);
});

test("Focus 2.0 v5 renders Bollinger plus short future trigger segments and compact labels", () => {
  assert.match(chart, /mode === "aster-detail" \? \["bb"\]/);
  assert.match(chart, /activeIndicators\.includes\("bb"\)/);
  assert.match(chart, /priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false/);
  assert.match(chart, /focusSegmentRefs/);
  assert.match(chart, /DCA \/ SHORT SYNC/);
  assert.match(chart, /SHORT RELEASE/);
  assert.match(chart, /BREAK-EVEN/);
  assert.match(chart, /distanceLabel/);
  assert.match(chart, /hedgeState/);
  assert.doesNotMatch(chart, /\[datasetVersion[^\]]*cockpit[^\]]*\]/s);
});

test("Focus 2.0 chart auto follows with right-side breathing room and can pause", () => {
  assert.match(chart, /setVisibleLogicalRange\(\{from:Math\.max\(0,chartCandles\.length-50\),to:chartCandles\.length\+18\}\)/);
  assert.match(chart, /setAutoFollow\(false\)/);
  assert.match(chart, /NAAR LIVE/);
  assert.match(chart, /pointerdown/);
  assert.match(chart, /touchstart/);
});

test("Focus 2.0 markers keep long, DCA and hedge actions explicit", () => {
  assert.match(chart, /"BUY"/);
  assert.match(chart, /`DCA\$\{one\.dcaNumber/);
  assert.match(chart, /"HEDGE"/);
  assert.match(chart, /"SHORT RELEASE"/);
  assert.match(chart, /"DCA \/ HEDGE"/);
});

test("trade detail consumes the server-side Focus 2.0 v5 cockpit", () => {
  assert.match(recent, /focusV2Cockpit/);
  assert.match(recent, /FocusV2CockpitPanel/);
  assert.match(recent, /Laatste DCA/);
  assert.match(recent, /Volgende DCA/);
  assert.match(recent, /SHORT release/);
  assert.match(recent, /Hedge state/);
  assert.match(recent, /Hedge target qty/);
  assert.match(recent, /Actuele SHORT/);
  assert.match(recent, /Winst sinds harvest/);
});

test("trade detail supports guarded mobile double-tap back without desktop double-click close", () => {
  assert.doesNotMatch(recent, /onDoubleClick=\{closeDetail\}/);
  assert.match(recent, /handleDetailTouchStart/);
  assert.match(recent, /handleDetailTouchMove/);
  assert.match(recent, /handleDetailTouchEnd/);
  assert.match(recent, /Math\.hypot\(touch\.clientX-detailTouchRef\.current\.x/);
  assert.match(recent, /now-previous\.at<=360/);
  assert.match(recent, /detailTargetIsInteractive/);
  assert.match(recent, /onClick=\{closeDetail\}/);
  assert.match(recent, /dubbel tikken of × om terug te gaan/);
});
test("historical Focus 2.0 rows keep opposite-side hedge history", () => {
  assert.match(chart, /const focusV2Main = String\(selection\.strategy2Role/);
  assert.doesNotMatch(chart, /FOCUS_V2_LONG" && !selection\.closedAt/);
  assert.match(chart, /hedgeAnchor/);
  assert.match(recent, /historicalFocusV2/);
  assert.match(recent, /s2fv2-/);
});
