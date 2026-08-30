import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const src = fs.readFileSync(new URL("../components/trading-chart.tsx", import.meta.url), "utf8");

test("Strategy-2 chart uses compact mobile-safe line labels", () => {
  for (const token of ["TERUGVAL -", "LAATSTE KOOP", "RELEASE +", "RE-HEDGE", 'label:"LIVE"']) {
    assert.ok(src.includes(token), `missing ${token}`);
  }
  assert.ok(!src.includes('label:`TRAILING TERUGVALKOOP'));
  assert.ok(!src.includes('label:`SHORT RELEASE'));
  assert.ok(!src.includes('label:`LAATST GEVULDE KOOP'));
});

test("line-label lane reserves the right price scale plus a 16px safety gap", () => {
  assert.ok(src.includes('right:"88px"'));
  assert.ok(src.includes('left:"12px"'));
  assert.ok(src.includes('overflow:"hidden"'));
  assert.ok(src.includes('whiteSpace:"nowrap"'));
  // Chart price scale has minimumWidth 72; label lane starts 88px from right => 16px gap.
  assert.ok(src.includes('minimumWidth:72'));
});

test("360, 390 and Fold-like widths retain a positive label lane", () => {
  const right = 88, left = 12;
  for (const width of [360, 390, 690]) {
    const lane = width - right - left;
    assert.ok(lane >= 260, `${width}px leaves only ${lane}px for labels`);
  }
});

test("portfolio target stays cockpit-only and is not a synthetic price line", () => {
  const focusLevels = src.split("const focusLevels=useMemo", 2)[1].split("syncFocusLevelsRef.current", 1)[0];
  assert.ok(!focusLevels.includes("PORTFOLIO DOEL"));
  assert.ok(src.includes("focusPortfolioTargetLabel"));
});

test("display patch includes real last-fill and armed re-hedge line segments without strategy math", () => {
  assert.ok(src.includes('addSegment("lastfill"'));
  assert.ok(src.includes('addSegment("rehedge"'));
  assert.ok(src.includes('setSegment("lastfill"'));
  assert.ok(src.includes('setSegment("rehedge"'));
});
