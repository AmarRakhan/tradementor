import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const v3 = fs.readFileSync(new URL("../components/aster-bot-configurator-v3.tsx", import.meta.url), "utf8");
const v2 = fs.readFileSync(new URL("../components/aster-bot-configurator-v2.tsx", import.meta.url), "utf8");
const shell = fs.readFileSync(new URL("../components/aster-strategy2-entry.tsx", import.meta.url), "utf8");
const version = fs.readFileSync(new URL("../lib/app-version.ts", import.meta.url), "utf8");
const history = fs.readFileSync(new URL("../lib/release-history.ts", import.meta.url), "utf8");

const slice = (source, start, end) => {
  const a = source.indexOf(start);
  const b = source.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, "missing source block: " + start);
  return source.slice(a, b);
};

test("Build 479 keeps prior release history plus Botconfigurator 3.1 references", () => {
  assert.match(version, /WEBAPP_BUILD_NUMBER = "479"/);
  assert.match(v3, /file_0000000064fc8210b631ce0a8caebb42/);
  assert.match(v3, /file_000000003b5081f4bee8a56187006a03/);
  assert.match(v3, /file_00000000113c82108f6f3daf44f3627e/);
  assert.match(history, /id: "v46-build-459-botconfigurator-v31"/);
  assert.match(history, /build: "459"/);
  assert.match(history, /id: "v46-build-462-legacy-seat-reset"/);
  assert.match(history, /id: "v46-build-461-v2-seat-reset"/);
  assert.match(history, /id: "v46-build-460-portfolio-tp-seat-reset"/);
});

test("current settings is rendered after the wizard actions and before the BETA release center", () => {
  const nav = v3.indexOf('<footer className="v3-nav">');
  const overview = v3.indexOf('className="v31-current"');
  const releases = v3.indexOf('className="v3-release-center"');
  assert.ok(nav >= 0 && overview > nav && releases > overview);
  assert.match(v3, /Huidige instellingen/);
  assert.match(v3, /Bekijk je actieve instellingen en pas ze snel aan/);
});

test("overview source is server-confirmed settings, never the unsaved wizard or quick draft", () => {
  assert.match(v3, /const \[confirmedSettings, setConfirmedSettings\] = useState<Record<string, unknown>>\(persisted\)/);
  assert.match(v3, /normalizeDraft\(confirmedSettings\)/);
  assert.match(v3, /data-source="server-confirmed"/);
  const overview = slice(v3, '{currentStep===1&&<section className="v31-current"', '{ownerBeta&&<details className="v3-release-center">');
  assert.match(overview, /confirmedDraft\.entryMarginLong/);
  assert.match(overview, /confirmedDraft\.longDcaAmount/);
  assert.doesNotMatch(overview, /quickDraft\./);
  assert.doesNotMatch(overview, /draft\.entryMargin/);
});

test("quick edit owns a local dirty draft that background server refresh cannot overwrite while dirty", () => {
  assert.match(v3, /const \[quickDraft, setQuickDraft\]/);
  assert.match(v3, /const \[quickDirty, setQuickDirty\]/);
  assert.match(v3, /if \(!quickDirty\) setQuickDraft\(normalizeQuickDraft\(persisted\)\)/);
  assert.match(v3, /setQuickDraft\(normalizeQuickDraft\(confirmedSettings\)\)/);
});

test("strategy is read-only in quick edit and can only be changed in the full wizard", () => {
  const quick = slice(v3, "if (quickEditOpen) {", 'return <article id="bot-configurator-v3" className="botconfig-v3"');
  assert.match(quick, /Kan hier niet worden gewijzigd/);
  assert.match(quick, /confirmedStrategyName/);
  assert.doesNotMatch(quick, /updateQuick\("zoneSoldiersEnabled"/);
  assert.match(v3, /chooseStrategy\(true\)/);
  assert.match(v3, /chooseStrategy\(false\)/);
});

test("quick edit max seats preserves the explicit Zone Warriors maximumPositions contract", () => {
  assert.match(v3, /id="v31-max-seats"/);
  assert.match(v3, /value=\{quickDraft\.maximumPositions\}/);
  assert.match(v3, /updateQuick\("maximumPositions",v\)/);
  assert.match(v3, /assertConfirmedSeatLimitFor\(quickDraft, confirmed\)/);
  assert.match(v3, /requestedMaximum/);
});

test("LONG and SHORT entry and DCA values remain independent", () => {
  for (const key of ["entryMarginLong","entryMarginShort","longDcaAmount","shortDcaAmount"]) {
    assert.match(v3, new RegExp('updateQuick\\("' + key + '"'));
  }
  assert.match(v3, /↑ LONG/);
  assert.match(v3, /↓ SHORT/);
});

test("cancel and restore never call the server", () => {
  const cancel = slice(v3, "const cancelQuickEdit = () => {", "const resetQuickEdit = () => {");
  const reset = slice(v3, "const resetQuickEdit = () => {", "async function saveQuickEdit()");
  assert.doesNotMatch(cancel, /authenticatedRequest/);
  assert.doesNotMatch(reset, /authenticatedRequest/);
  assert.match(cancel, /Wijzigingen niet opslaan/);
});

test("quick save uses only the existing state-preserving settings PUT and never starts stops or closes", () => {
  const save = slice(v3, "async function saveQuickEdit()", "const strategyName =");
  assert.match(save, /\/api\/exchanges\/aster\/strategy2\/settings/);
  assert.match(save, /method: "PUT"/);
  assert.doesNotMatch(save, /strategy2\/start/);
  assert.doesNotMatch(save, /strategy2\/stop/);
  assert.doesNotMatch(save, /close/i);
  assert.doesNotMatch(save, /POST/);
});

test("more settings exposes every existing advanced configuration family without fake runtime toggles", () => {
  for (const label of [
    "Markt & selectie", "Zone Warriors", "DCA", "Leverage", "Positiegrootte",
    "Instapfilters", "Exposure refill", "Bescherming", "Smart Rescue", "Take profit & basis",
    "Cycle start", "Huidige waarde", "Aangepast",
  ]) assert.match(v3, new RegExp(label.replace(/[&]/g, "\\&")));
  assert.match(v3, /Alleen lege capaciteit vullen en Auto-restart na TP zijn informatief/);
  assert.match(v3, /bewust geen fake schakelaars/);
});

test("V3 quick edit remains BETA-only and STABLE V2 stays untouched", () => {
  assert.match(shell, /release\?\.channel === "BETA"/);
  assert.match(shell, /BetaConfiguratorV3/);
  assert.match(shell, /BetaConfiguratorV2/);
  assert.doesNotMatch(v2, /v31-current/);
  assert.doesNotMatch(v2, /Instellingen wijzigen/);
  assert.doesNotMatch(v2, /file_0000000064fc8210b631ce0a8caebb42/);
});

test("mobile CSS explicitly protects compact 430px and 350px layouts from overflow", () => {
  assert.match(v3, /@media\(max-width:430px\)/);
  assert.match(v3, /@media\(max-width:350px\)/);
  assert.match(v3, /overflow:hidden/);
  assert.match(v3, /v31-current-grid/);
  assert.match(v3, /v31-setting-card/);
});
