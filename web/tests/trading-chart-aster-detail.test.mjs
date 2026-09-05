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
  assert.match(chart, /level\.key==="dca"/);
  assert.match(chart, /lineWidth:3/);
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
  assert.match(recent, /detailRuntime\?\.nextDcaDistancePct/);
  assert.match(recent, /detailRuntime\?\.tpPrice/);
  assert.match(recent, /detailRuntime\?\.tpDistancePct/);
  assert.match(recent, /detailRuntime\?\.expectedPnlAtTp/);
  assert.match(recent, /detailRuntime\?\.portfolioValueAtTp/);
  assert.doesNotMatch(recent, /nextDcaDistanceUsd|tpDistanceUsd/);
  assert.match(recent, /breakEvenPrice=\{detailBreakEvenPrice\}/);
  assert.match(recent, /dcaLevels=\{detailChartDcaLevels\}/);
  assert.match(recent, /plannedActionLevels=\{detailPlannedLevels\}/);
});

test("trade detail renders percentage-only live distances", () => {
  assert.match(recent, /const detailNextDcaDistancePct\s*=\s*finite\(detailRuntime\?\.nextDcaDistancePct\)/);
  assert.match(recent, /const detailTpDistancePct\s*=\s*finite\(detailRuntime\?\.tpDistancePct\)/);
  assert.match(recent, /const signedDistance\s*=/);
  assert.match(recent, /AFSTAND TOT DCA/);
  assert.match(recent, /AFSTAND TOT TP/);
  assert.doesNotMatch(recent, /Afstand tot DCA[^\n]*\$/);
});

test("trade detail shows configured TP and portfolio-at-TP without double-counting unrealized PnL", () => {
  assert.match(recent, /Take Profit ingesteld/);
  assert.match(recent, /Verwachte winst bij TP/);
  assert.match(recent, /Portfoliowaarde bij TP/);
  assert.match(recent, /accountDisplay\.equityNumber\s*\+\s*\(detailExpectedPnlAtTp\s*-\s*detailPnl\)/);
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
  assert.match(recent, /Math\.hypot\(touch\.clientX\s*-\s*detailTouchRef\.current\.x/);
  assert.match(recent, /now\s*-\s*previous\.at\s*<=\s*360/);
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

test("Multi DCA managed positions override stale Focus role and keep DCA TP overlays visible", () => {
  assert.match(recent, /detailManagedByMultiDca/);
  assert.match(recent, /managedByMultiDca\s*\?\s*"MULTI_DCA"/);
  assert.match(recent, /!detailManagedByMultiDca\s*&&\s*String\(detail\.selection\.strategy2Role/);
  assert.match(chart, /focusV2\?"Focus 2\.0":"Strategy 2 Multi DCA"/);
  assert.match(chart, /chartOverlayLevels=focusV2\?focusLevels:plannedOverlayLevels/);
});

test("trade detail shows the compact reference cockpit above the chart", () => {
  assert.match(recent, /Actuele Strategy 2 tradegegevens/);
  assert.match(recent, /HUIDIGE PNL/);
  assert.match(recent, /MARGIN IN TRADE/);
  assert.match(recent, /WINST BIJ TP/);
  assert.match(recent, /PORTFOLIO BIJ TP/);
  assert.match(recent, /DCA STATUS/);
  assert.match(recent, /TP INSTELLING/);
  assert.match(recent, /AFSTAND TOT DCA/);
  assert.match(recent, /AFSTAND TOT TP/);
  assert.match(recent, /DCA GEVULD/);
  assert.match(recent, /detailPnlPct/);
});
