import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const maker = readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const route = readFileSync(new URL("../app/api/exchanges/aster/strategy2/leverage-tiers/route.ts", import.meta.url), "utf8");

test("direct manual coin settings load server-authoritative Aster leverage tiers", () => {
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

test("direct settings blocks selected coins below Aster minimum order", () => {
  assert.match(maker, /entryOrderValid === false/);
  assert.match(maker, /startmargin voldoet niet aan de actuele Aster minimumorder/);
  assert.match(maker, /suggestedEntryMarginUsd/);
  assert.match(maker, /minimumEntryMarginUsd/);
});

test("wizard is removed and all bot settings are directly visible", () => {
  assert.doesNotMatch(maker, /maker-overlay/);
  assert.doesNotMatch(maker, /Strategy Maker openen/);
  assert.match(maker, /Alle actieve instellingen staan direct hieronder/);
  assert.match(maker, /LONG slots \(max 25\)/);
  assert.match(maker, /SHORT slots \(max 25\)/);
  assert.match(maker, /Globale DCA-limiet \(0–\$\{MAX_DCA\}\)/);
});
