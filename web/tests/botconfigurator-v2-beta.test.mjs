import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const shell = fs.readFileSync(new URL("../components/aster-strategy2-entry.tsx", import.meta.url), "utf8");
const ui = fs.readFileSync(new URL("../components/aster-bot-configurator-v2.tsx", import.meta.url), "utf8");
const page = fs.readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");

test("BETA release gate remains backwards compatible and isolated", () => {
  assert.match(shell, /features\?\.bot_configurator_v2\?\.enabled/);
  assert.match(shell, /if \(!releaseEnabled\) return <AsterStrategy2Maker/);
  assert.match(shell, /lazy\(\(\) => import\("@\/components\/aster-bot-configurator-v2"\)/);
  assert.match(ui, /data-beta-only="true"/);
});

test("Botconfigurator 3.0 has exactly four visible wizard steps", () => {
  assert.match(ui, /\["strategy", "Strategie"\]/);
  assert.match(ui, /\["settings", "Instellingen"\]/);
  assert.match(ui, /\["entry", "Instap & DCA"\]/);
  assert.match(ui, /\["review", "Controleren"\]/);
  assert.doesNotMatch(ui, /\["markt", "Markt"\]/);
  assert.doesNotMatch(ui, /\["dca", "DCA"\]/);
  assert.doesNotMatch(ui, /\["bescherming", "Bescherming"\]/);
  assert.match(ui, /currentStep===1/);
  assert.match(ui, /currentStep===4/);
});

test("all binding Set A and Set B visual references are embedded", () => {
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
  ]) assert.match(ui, new RegExp(id));
});

test("display strategy names are Zone Warriors and Classic DCA and Sniper is absent", () => {
  assert.match(ui, />Zone Warriors</);
  assert.match(ui, />Classic DCA</);
  assert.doesNotMatch(ui, />Sniper</);
  assert.match(page, /STRATEGIE · ZONE WARRIORS/);
  assert.match(page, /STRATEGIE · CLASSIC DCA/);
  assert.doesNotMatch(page, /STRATEGIE · PRIJSZONE-STOELEN/);
});

test("internal strategy and persistence identifiers remain unchanged", () => {
  assert.match(ui, /engine: "multi_bb_v1"/);
  assert.match(ui, /strategyKind: "multi_bb_v1"/);
  assert.match(ui, /zoneSoldiersEnabled: draft\.zoneSoldiersEnabled/);
  assert.match(ui, /zoneSoldiersOptInVersion: draft\.zoneSoldiersEnabled \? 1 : 0/);
  assert.match(ui, /\/api\/exchanges\/aster\/strategy2\/settings/);
  assert.match(ui, /\/api\/exchanges\/aster\/strategy2\/start/);
});

test("LONG and SHORT keep independent start and DCA configuration", () => {
  for (const key of ["entryMarginLong","entryMarginShort","longDcaAmount","shortDcaAmount","longDcaDistance","shortDcaDistance","maxDcaLong","maxDcaShort"]) {
    assert.match(ui, new RegExp(key));
  }
  assert.match(ui, /DCA-bedrag/);
  assert.match(ui, /DCA-afstand/);
  assert.match(ui, /Max DCA/);
});

test("TP modes and portfolio TP base semantics stay reachable", () => {
  assert.match(ui, /"PER_TRADE","PORTFOLIO","OFF"/);
  assert.match(ui, /portfolioTpBaseMode/);
  assert.match(ui, /portfolioTpCustomBaseEquity/);
  assert.match(ui, /Cycle start/);
  assert.match(ui, /Huidige waarde/);
  assert.match(ui, /Aangepast/);
});

test("all requested accordion groups remain functional controls", () => {
  for (const label of ["Markt & selectie","Leverage","Positiegrootte","Instapfilters","Smart Rescue DCA","Bescherming & exposure","Refill & heropenen"]) {
    assert.match(ui, new RegExp(label.replace(/[&]/g, "\\&")));
  }
  assert.match(ui, /settingsAccordion/);
  assert.match(ui, /entryAccordion/);
  assert.match(ui, /aria-expanded=\{open\}/);
});

test("refill panel does not invent fake configurable runtime rules", () => {
  assert.match(ui, /Alleen lege capaciteit vullen/);
  assert.match(ui, /Auto-restart na TP/);
  assert.match(ui, /runtime-regel/);
  assert.match(ui, /bewust geen fake schakelaars/);
  assert.match(ui, /checked=\{draft\.exposureRefillEnabled\}/);
});

test("owner release center remains outside the four-step flow and does not auto-publish", () => {
  assert.match(ui, /Releasecentrum · BETA-owner/);
  assert.match(ui, /STABLE wordt niet automatisch gewijzigd/);
  assert.match(ui, /Getest en akkoord/);
  assert.match(ui, /Vrijgeven/);
  assert.match(ui, /Terug naar BETA/);
});
