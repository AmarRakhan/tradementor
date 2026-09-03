import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

test("manual and automatic selection keep one consistent margin sizing meaning", () => {
  assert.match(maker, /Start margin \(USDT\)/);
  assert.match(maker, /entrySizingMode:\s*"margin"/);
  assert.match(maker, /entryMarginUsd:\s*n\(v\.entryMargin\)/);
  assert.doesNotMatch(maker, /entrySizingMode:\s*v\.manualEnabled/);
});

test("direct settings accept DCA limits such as 10 and cap extreme values at 500", () => {
  assert.match(maker, /Globale DCA-limiet \(0–\$\{MAX_DCA\}\)/);
  assert.match(maker, /maxDca:\s*clampInt\(n\(v\.maxDca\), 0, MAX_DCA\)/);
  assert.match(maker, /unlimitedDca:\s*false/);
  assert.match(maker, /Globale DCA-limiet mag maximaal \$\{MAX_DCA\} zijn/);
  assert.doesNotMatch(maker, /Onbeperkt DCA/);
});

test("manual entries still use server-authoritative minimum-order previews before start", () => {
  assert.match(maker, /strategy2\/leverage-tiers/);
  assert.match(maker, /entryOrderValid === false/);
  assert.match(maker, /startmargin voldoet niet aan de actuele Aster minimumorder/);
  assert.match(maker, /suggestedEntryMarginUsd/);
});

test("automatic entries cannot silently submit below the common Aster minimum order", () => {
  assert.match(maker, /settings\.entryMarginUsd \* settings\.minimumLeverage < 5/);
  assert.match(maker, /Startmargin te laag/);
});
