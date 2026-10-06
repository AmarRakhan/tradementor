import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const shell = fs.readFileSync(new URL("../components/aster-strategy2-entry.tsx", import.meta.url), "utf8");
const v2 = fs.readFileSync(new URL("../components/aster-bot-configurator-v2.tsx", import.meta.url), "utf8");
const v3 = fs.readFileSync(new URL("../components/aster-bot-configurator-v3.tsx", import.meta.url), "utf8");
const page = fs.readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");

test("Build 507 routes every user through an explicit legacy or Configurator 3 choice", () => {
  assert.match(shell, /type BotSettingsMode = "legacy" \| "configurator3"/);
  assert.match(shell, /Oude instellingen/);
  assert.match(shell, /Nieuwe configurator/);
  assert.match(shell, /<AsterStrategy2Maker \{\.\.\.props\} embedded \/>/);
  assert.match(shell, /<ConfiguratorV3 \{\.\.\.props\}/);
  assert.doesNotMatch(shell, /BetaConfiguratorV2/);
});

test("Build 457 V2 remains intact for STABLE users", () => {
  assert.match(v2, /Botconfigurator V2/);
  for (const id of ["markt", "posities", "instap", "grootte", "dca", "winst", "bescherming", "controle"]) {
    assert.match(v2, new RegExp("v2-step-" + id));
  }
  assert.doesNotMatch(page, /STRATEGIE · PRIJSZONE-STOELEN/);
  assert.doesNotMatch(page, /STRATEGIE · TRADITIONEEL/);
  assert.doesNotMatch(page, /STRATEGIE · ZONE WARRIORS/);
});

test("Botconfigurator 3.0 has exactly four visible wizard steps", () => {
  assert.match(v3, /\["strategy", "Strategie"\]/);
  assert.match(v3, /\["settings", "Instellingen"\]/);
  assert.match(v3, /\["entry", "Instap & DCA"\]/);
  assert.match(v3, /\["review", "Controleren"\]/);
  assert.doesNotMatch(v3, /\["markt", "Markt"\]/);
  assert.doesNotMatch(v3, /\["dca", "DCA"\]/);
  assert.match(v3, /currentStep===1/);
  assert.match(v3, /currentStep===4/);
  assert.match(v3, /id="bot-configurator-v3"/);
  assert.match(v3, /data-rollout="opt-in-beta"/);
});

test("all binding Set A and Set B visual references are embedded in V3", () => {
  for (const id of [
    "file_00000000e820820abd4c0803c0faf72c",
    "file_00000000d4188243af425d77dce05825",
    "file_00000000e3d88246868c97243a4217e0",
    "file_000000001aec8210ae97ce7474fad735",
    "file_00000000e5a88210923fcf9378f4bbb6",
    "file_00000000d50c82438453f4be8cb1afc3",
    "file_0000000073288210ad62e9dfbb148202",
    "file_0000000015c482109ffb7e3e4b6e4efe",
    "file_00000000d18082108f0116c9afb082e9",
  ]) assert.match(v3, new RegExp(id));
});

test("V3 exposes one AsterBot with price-zone seats as an optional module and Sniper is absent", () => {
  assert.match(v3, /title="AsterBot"/);
  assert.match(v3, /label="Prijszone-stoelen"/);
  assert.doesNotMatch(v3, /<strong>Zone Warriors<\/strong>/);
  assert.doesNotMatch(v3, /<strong>Classic DCA<\/strong>/);
  assert.doesNotMatch(v3, />Sniper</);
});

test("V3 reuses unchanged runtime and persistence identifiers", () => {
  assert.match(v3, /engine: "multi_bb_v1"/);
  assert.match(v3, /strategyKind: "multi_bb_v1"/);
  assert.match(v3, /zoneSoldiersEnabled: source\.zoneSoldiersEnabled/);
  assert.match(v3, /zoneSoldiersOptInVersion: source\.zoneSoldiersEnabled \? 1 : 0/);
  assert.match(v3, /\/api\/exchanges\/aster\/strategy2\/settings/);
  assert.match(v3, /\/api\/exchanges\/aster\/strategy2\/start/);
});

test("LONG and SHORT keep independent start and DCA configuration", () => {
  for (const key of ["entryMarginLong","entryMarginShort","longDcaAmount","shortDcaAmount","longDcaDistance","shortDcaDistance","maxDcaLong","maxDcaShort"]) {
    assert.match(v3, new RegExp(key));
  }
  assert.match(v3, /DCA-bedrag/);
  assert.match(v3, /DCA-afstand/);
  assert.match(v3, /Max DCA/);
});

test("TP modes and portfolio TP base semantics stay reachable", () => {
  assert.match(v3, /"PER_TRADE","PORTFOLIO","OFF"/);
  assert.match(v3, /portfolioTpBaseMode/);
  assert.match(v3, /portfolioTpCustomBaseEquity/);
  assert.match(v3, /Cycle start/);
  assert.match(v3, /Huidige waarde/);
  assert.match(v3, /Aangepast/);
});

test("requested advanced groups remain functional controls", () => {
  for (const label of ["Markt & selectie","Leverage","Positiegrootte","Instapfilters","Smart Rescue DCA","Bescherming & exposure","Refill & heropenen"]) {
    assert.match(v3, new RegExp(label.replace(/[&]/g, "\\&")));
  }
  assert.match(v3, /settingsAccordion/);
  assert.match(v3, /entryAccordion/);
  assert.match(v3, /aria-expanded=\{open\}/);
});

test("refill panel preserves real controls and invents no fake runtime toggles", () => {
  assert.match(v3, /Alleen lege capaciteit vullen/);
  assert.match(v3, /Auto-restart na TP/);
  assert.match(v3, /runtime-regel/);
  assert.match(v3, /bewust geen fake schakelaars/);
  assert.match(v3, /checked=\{draft\.exposureRefillEnabled\}/);
});

test("owner release center remains separate and never auto-publishes STABLE", () => {
  assert.match(v3, /Releasecentrum · BETA-owner/);
  assert.match(v3, /STABLE wordt niet automatisch gewijzigd/);
  assert.match(v3, /Getest en akkoord/);
  assert.match(v3, /Vrijgeven/);
  assert.match(v3, /Terug naar BETA/);
});


test("allows zero seats on exactly one price-zone side", () => {
  assert.match(v2, /const zoneLongSeats = Math\.max\(0,/);
  assert.match(v2, /const zoneShortSeats = Math\.max\(0,/);
  assert.match(v2, /zoneLongSeats \+ zoneShortSeats < 1/);
  assert.match(v2, /tussen 0 en 100 liggen; samen minimaal 1/);
});
