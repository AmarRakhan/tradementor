import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

test("manual and automatic selection keep margin sizing with side-specific entries", () => {
  assert.match(maker, /Instap LONG/);
  assert.match(maker, /Instap SHORT/);
  assert.match(maker, /entrySizingMode:\s*"margin"/);
  assert.match(maker, /entryMarginLongUsd:\s*longEntry/);
  assert.match(maker, /entryMarginShortUsd:\s*shortEntry/);
  assert.doesNotMatch(maker, /entrySizingMode:\s*v\.manualEnabled/);
});

test("direct settings accept independent DCA limits and cap extreme values at 500", () => {
  assert.match(maker, /Max DCA LONG/);
  assert.match(maker, /Max DCA SHORT/);
  assert.match(maker, /maxDcaLong:\s*maxLong/);
  assert.match(maker, /maxDcaShort:\s*maxShort/);
  assert.match(maker, /unlimitedDca:\s*false/);
  assert.match(maker, /Max DCA mag maximaal \$\{MAX_DCA\} zijn/);
});

test("manual entries still use server-authoritative minimum-order previews before start", () => {
  assert.match(maker, /strategy2\/leverage-tiers/);
  assert.match(maker, /entryOrderValid === false/);
  assert.match(maker, /instapmargin voldoet niet aan de actuele Aster minimumorder/);
  assert.match(maker, /suggestedEntryMarginUsd/);
});

test("automatic entries do not size against the configured minimum leverage", () => {
  assert.doesNotMatch(maker, /entryMarginLongUsd \* settings\.minimumLeverage < 5/);
  assert.doesNotMatch(maker, /entryMarginShortUsd \* settings\.minimumLeverage < 5/);
  assert.match(maker, /entryMarginLongUsd <= 0/);
  assert.match(maker, /entryMarginShortUsd <= 0/);
  assert.match(maker, /actual maximum valid leverage/);
  assert.match(maker, /skips symbols whose Aster/);
});
