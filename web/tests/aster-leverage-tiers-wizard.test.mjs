import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const maker = readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const route = readFileSync(new URL("../app/api/exchanges/aster/strategy2/leverage-tiers/route.ts", import.meta.url), "utf8");

test("manual coin settings load server-authoritative Aster leverage tiers", () => {
  assert.match(maker, /strategy2\/leverage-tiers/);
  assert.match(maker, /entryPlan/);
  assert.match(maker, /currentLeverage/);
  assert.match(route, /proxyStrategy2Live/);
});

test("direct settings panel keeps exchange leverage authoritative", () => {
  assert.match(maker, /Leverage tiers konden niet worden geladen/);
  assert.match(maker, /entryOrderValid === false/);
  assert.doesNotMatch(maker, /HYPE boven \$3000/);
});

test("selected coins below Aster minimum order remain blocked", () => {
  assert.match(maker, /entryOrderValid === false/);
  assert.match(maker, /instapmargin voldoet niet aan de actuele Aster minimumorder/);
  assert.match(maker, /suggestedEntryMarginUsd/);
  assert.match(maker, /minimumEntryMarginUsd/);
});

test("all primary bot settings are directly visible without a wizard", () => {
  assert.doesNotMatch(maker, /maker-overlay|Strategy Maker openen/);
  assert.match(maker, /label="LONG slots"/);
  assert.match(maker, /label="SHORT slots"/);
  assert.match(maker, /Max DCA LONG/);
  assert.match(maker, /Max DCA SHORT/);
  assert.match(maker, /LONG \/ SHORT · DCA & Take Profit/);
});
