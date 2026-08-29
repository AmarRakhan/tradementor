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
  assert.match(chart, /REL/);
  assert.match(chart, /HEDGE/);
});

test("Focus 2.0 does not duplicate legacy detail overlays", () => {
  assert.match(chart, /if \(mode === "aster-detail" && !focusV2\)/);
});

test("Focus 2.0 v5 renders only short future trigger segments and compact chips", () => {
  assert.match(chart, /activeIndicators\.includes\("bb"\)&&!focusV2/);
  assert.match(chart, /const addSegment=/);
  assert.match(chart, /priceLineVisible:false,lastValueVisible:true/);
  assert.match(chart, /segmentEnd/);
  assert.match(chart, /DCA \+ SHORT BIJ/);
  assert.match(chart, /SHORT LOS/);
  assert.match(chart, /stateVersion>=5/);
  const focusBlock=chart.slice(chart.indexOf("if(focusV2&&cockpit){"),chart.indexOf("} else currentPriceLineRef.current=null",chart.indexOf("if(focusV2&&cockpit){")));
  assert.doesNotMatch(focusBlock,/createPriceLine/);
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
  assert.match(chart, /"REL"/);
});

test("trade detail consumes the server-side Focus 2.0 cockpit", () => {
  assert.match(recent, /focusV2Cockpit/);
  assert.match(recent, /FocusV2CockpitPanel/);
  assert.match(recent, /VOLGENDE BOTACTIE|nextAction/);
  assert.match(recent, /LAATSTE ACTIES/);
  assert.match(recent, /5m Bollinger-middle/);
});

test("historical Focus 2.0 rows keep opposite-side hedge history", () => {
  assert.match(chart, /const focusV2Main = String\(selection\.strategy2Role/);
  assert.doesNotMatch(chart, /FOCUS_V2_LONG" && !selection\.closedAt/);
  assert.match(chart, /hedgeAnchor/);
  assert.match(recent, /historicalFocusV2/);
  assert.match(recent, /s2fv2-/);
});
