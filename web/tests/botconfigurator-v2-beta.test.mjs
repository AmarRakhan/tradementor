import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const shell = fs.readFileSync(new URL("../components/aster-strategy2-entry.tsx", import.meta.url), "utf8");
const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const v2 = fs.readFileSync(new URL("../components/aster-bot-configurator-v2.tsx", import.meta.url), "utf8");
const v3 = fs.readFileSync(new URL("../components/aster-bot-configurator-v3.tsx", import.meta.url), "utf8");
const page = fs.readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");

test("Build 544 routes Botinstellingen through one classic AsterBot surface", () => {
  assert.match(shell, /<AsterStrategy2Maker \{\.\.\.props\} \/>/);
  assert.doesNotMatch(shell, /Oude instellingen|Nieuwe configurator|configurator3|ConfiguratorV3/);
  assert.match(maker, /ASTER BOT/);
  assert.match(maker, /Botinstellingen/);
});

test("retained V2 and V3 source remain non-live migration references", () => {
  assert.match(v2, /Botconfigurator V2/);
  assert.match(v3, /id="bot-configurator-v3"/);
  assert.doesNotMatch(shell, /aster-bot-configurator-v2/);
  assert.doesNotMatch(shell, /aster-bot-configurator-v3/);
});

test("classic AsterBot exposes price-zone seats as an optional module", () => {
  assert.match(maker, /Prijszone-stoelen/);
  assert.match(maker, /LONG per prijszone/);
  assert.match(maker, /SHORT per prijszone/);
  assert.match(maker, /priceZoneSeats:\s*\{/);
  assert.doesNotMatch(maker, /Warrior/i);
  assert.doesNotMatch(page, /STRATEGIE · ZONE WARRIORS/);
});

test("price-zone seat counts allow zero on exactly one side", () => {
  assert.match(maker, /clampInt\(n\(v\.priceZoneLongSeats\), 0, 100\)/);
  assert.match(maker, /clampInt\(n\(v\.priceZoneShortSeats\), 0, 100\)/);
  assert.match(maker, /zoneLong \+ zoneShort < 1/);
  assert.match(maker, /samen minimaal 1 stoel/);
});

test("LONG and SHORT keep independent start and DCA configuration", () => {
  for (const key of ["entryMarginLong","entryMarginShort","longDcaAmount","shortDcaAmount","longDcaDistance","shortDcaDistance","maxDcaLong","maxDcaShort"]) {
    assert.match(maker, new RegExp(key));
  }
});

test("TP modes and Portfolio TP remain in the classic settings surface", () => {
  assert.match(maker, /"PER_TRADE" \| "PORTFOLIO" \| "OFF"/);
  assert.match(maker, /portfolioTpBaseMode/);
  assert.match(maker, /portfolioTpCustomBaseEquity/);
  assert.match(maker, /Portfolio Take Profit/);
});
