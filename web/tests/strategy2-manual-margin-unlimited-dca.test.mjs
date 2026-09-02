import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

test("manual selection still uses margin sizing while automatic mode keeps notional sizing", () => {
  assert.match(maker, /Start margin \(USDT\)/);
  assert.match(maker, /entrySizingMode:\s*v\.manualEnabled \? "margin" : "notional"/);
  assert.match(maker, /entryMarginUsd:\s*v\.manualEnabled/);
});

test("direct settings enforce a global DCA ceiling of three and disable unlimited DCA", () => {
  assert.match(maker, /Globale DCA-limiet \(0–3\)/);
  assert.match(maker, /maxDca:\s*clampInt\(n\(v\.maxDca\), 0, 3\)/);
  assert.match(maker, /unlimitedDca:\s*false/);
  assert.match(maker, /Globale DCA-limiet mag maximaal 3 zijn/);
  assert.doesNotMatch(maker, /Onbeperkt DCA/);
});

test("manual entries still use server-authoritative minimum-order previews before start", () => {
  assert.match(maker, /strategy2\/leverage-tiers/);
  assert.match(maker, /entryOrderValid === false/);
  assert.match(maker, /startmargin voldoet niet aan de actuele Aster minimumorder/);
  assert.match(maker, /suggestedEntryMarginUsd/);
});
