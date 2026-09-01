import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const chart = readFileSync(new URL("../components/trading-chart.tsx", import.meta.url), "utf8");
const recent = readFileSync(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");

test("Aster detail chart keeps executed markers and adds planned DCA/TP overlays", () => {
  assert.match(chart, /title:\s*"WINST VANAF"/);
  assert.match(chart, /plannedActionLevels/);
  assert.match(chart, /plannedOverlayLevels/);
  assert.match(chart, /VOLGENDE \$\{selection\.side\.toUpperCase\(\)\} DCA/);
  assert.match(chart, /level\.key==="tp"/);
  assert.match(chart, /axisLabelVisible:false/);
  assert.match(chart, /layoutFocusLabelYs/);
  assert.match(chart, /dcaLevels/);
  assert.doesNotMatch(chart, /group\.events\[0\]\?\.kind==="dca"\?"ADD"/);
  assert.doesNotMatch(chart, /entrySeries\.setData/);
});

test("open detail consumes server Strategy 2 next-action preview values", () => {
  assert.match(recent, /strategy2Tp\?\.breakEvenPrice/);
  assert.match(recent, /strategy2DcaLadder\?\.levels/);
  assert.match(recent, /multiDcaPositions/);
  assert.match(recent, /detailRuntime\?\.nextDcaPrice/);
  assert.match(recent, /detailRuntime\?\.nextDcaDistanceUsd/);
  assert.match(recent, /detailRuntime\?\.nextDcaDistancePct/);
  assert.match(recent, /detailRuntime\?\.tpPrice/);
  assert.match(recent, /detailRuntime\?\.tpDistanceUsd/);
  assert.match(recent, /detailRuntime\?\.tpDistancePct/);
  assert.match(recent, /detailRuntime\?\.expectedPnlAtTp/);
  assert.match(recent, /detailRuntime\?\.portfolioValueAtTp/);
  assert.match(recent, /breakEvenPrice=\{detailBreakEvenPrice\}/);
  assert.match(recent, /dcaLevels=\{detailChartDcaLevels\}/);
  assert.match(recent, /plannedActionLevels=\{detailPlannedLevels\}/);
});

test("trade detail renders positive direction-aware LONG and SHORT distances", () => {
  assert.match(recent, /Math\.abs\(usd\)/);
  assert.match(recent, /Math\.abs\(pctValue\)/);
  assert.match(recent, /detailMainSide==="LONG"&&kind==="DCA"/);
  assert.match(recent, /detailMainSide==="SHORT"&&kind==="TP"/);
  assert.match(recent, /down\?"dalen":"stijgen"/);
  assert.match(recent, /Afstand tot volgende DCA/);
  assert.match(recent, /Afstand tot TP/);
});

test("trade detail shows configured TP and portfolio-at-TP without double-counting unrealized PnL", () => {
  assert.match(recent, /Take Profit ingesteld/);
  assert.match(recent, /Verwachte winst bij TP/);
  assert.match(recent, /Portfoliowaarde bij TP/);
  assert.match(recent, /accountDisplay\.equityNumber\+\(detailExpectedPnlAtTp-detailPnl\)/);
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

test("Aster detail chart still provides Bollinger market context", () => {
  assert.match(chart, /mode === "aster-detail" \? \["bb"\]/);
  assert.match(chart, /activeIndicators\.includes\("bb"\)/);
  assert.match(chart, /priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false/);
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
