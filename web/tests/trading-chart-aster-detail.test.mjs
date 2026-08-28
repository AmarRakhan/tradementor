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


test("Aster trade detail defaults to one minute and keeps hedge markers quiet", () => {
  assert.match(chart, /useState\(mode === "aster-detail" \? "1m" : "15m"\)/);
  assert.match(chart, /onlyHedge\?""/);
  assert.doesNotMatch(chart, /\?"HEDGE \+":"HEDGE -"/);
});
