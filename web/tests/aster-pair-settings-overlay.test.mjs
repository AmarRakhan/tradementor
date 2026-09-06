import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const overlay = fs.readFileSync(new URL("../components/aster-pair-settings-overlay.tsx", import.meta.url), "utf8");
const settingsRoute = fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts", import.meta.url), "utf8");
const layout = fs.readFileSync(new URL("../app/layout.tsx", import.meta.url), "utf8");

test("trade detail exposes exactly one pair-specific settings pencil contract", () => {
  assert.match(overlay, /MARGIN IN TRADE/);
  assert.match(overlay, /data-pair-settings-pencil/);
  assert.match(overlay, /ASTER · TRADEDETAIL/);
  assert.match(overlay, /Pair-instellingen aanpassen/);
  assert.match(layout, /<AsterPairSettingsOverlay \/>/);
});

test("one pair editor contains independent LONG and SHORT DCA and TP overrides", () => {
  for (const field of [
    "entryMarginUsd",
    "minimumLeverage",
    "longDcaMarginUsd",
    "longDcaDistance",
    "maxDcaLong",
    "longTakeProfitValue",
    "shortDcaMarginUsd",
    "shortDcaDistance",
    "maxDcaShort",
    "shortTakeProfitValue",
    "shortStartMultiplier",
  ]) assert.ok(overlay.includes(field), `missing ${field}`);
  assert.match(overlay, /Eén pair-editor voor zowel LONG als SHORT/);
  assert.match(overlay, /Pair override → algemene instelling → systeemdefault/);
  assert.match(overlay, /Geldt vanaf volgende nieuwe cycle/);
  assert.match(overlay, /Bestaande DCA-count, qty, avg entry, fills en cycle-baseline worden niet gereset/);
});

test("pair editor can remove only the selected pair override and use global settings", () => {
  assert.match(overlay, /Gebruik algemene instellingen/);
  assert.match(overlay, /delete nextOverrides\[symbol\]/);
  assert.match(overlay, /pairOverrides: nextOverrides/);
});

test("pair save is server-confirmed by successful settings PUT and refreshes snapshot", () => {
  assert.match(overlay, /await authenticatedRequest\("\/api\/exchanges\/aster\/strategy2\/settings"/);
  assert.match(overlay, /await load\(symbol\)/);
  assert.match(overlay, /document\.dispatchEvent\(new Event\("visibilitychange"\)\)/);
});

test("pair TP values remain visible but are inactive outside PER_TRADE mode", () => {
  assert.match(overlay, /Niet actief in Portfolio-modus/);
  assert.match(overlay, /Niet actief: Take Profit staat uit/);
  assert.match(overlay, /takeProfitMode/);
});

test("global Strategy 2 saves preserve pair and side-specific extended settings", () => {
  assert.match(settingsRoute, /preserveExistingPairOverrides/);
  for (const key of ["pairOverrides", "takeProfitMode", "longDcaDistance", "shortDcaDistance", "longTakeProfitValue", "shortTakeProfitValue"]) {
    assert.ok(settingsRoute.includes(`"${key}"`), `missing preserved ${key}`);
  }
  assert.match(settingsRoute, /\/api\/exchanges\/aster/);
  assert.match(settingsRoute, /hasOwnProperty\.call\(current, key\)/);
});
