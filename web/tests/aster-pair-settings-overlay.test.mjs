import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const overlay = fs.readFileSync(new URL("../components/aster-pair-settings-overlay.tsx", import.meta.url), "utf8");
const settingsRoute = fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts", import.meta.url), "utf8");
const layout = fs.readFileSync(new URL("../app/layout.tsx", import.meta.url), "utf8");

test("trade detail exposes a pair-specific settings pencil", () => {
  assert.match(overlay, /MARGIN IN TRADE/);
  assert.match(overlay, /data-pair-settings-pencil/);
  assert.match(overlay, /ASTER · TRADEDETAIL/);
  assert.match(overlay, /Pair-instellingen aanpassen/);
  assert.match(layout, /<AsterPairSettingsOverlay \/>/);
});

test("pair editor exposes sparse DCA, TP and next-cycle overrides", () => {
  for (const field of [
    "entryMarginUsd",
    "minimumLeverage",
    "dcaMarginUsd",
    "dcaDistance",
    "maxDca",
    "takeProfit",
    "takeProfitEnabled",
    "shortStartMultiplier",
  ]) assert.ok(overlay.includes(field), `missing ${field}`);
  assert.match(overlay, /Niet-aangevinkte velden blijven de basissettings volgen/);
  assert.match(overlay, /Geldt vanaf volgende nieuwe cyclus/);
  assert.match(overlay, /Uitgevoerde fills worden nooit achteraf aangepast/);
});

test("pair save is server-confirmed and refreshes the Aster snapshot", () => {
  assert.match(overlay, /\/api\/exchanges\/aster\/strategy2\/settings/);
  assert.match(overlay, /Server heeft de pair-instellingen niet bevestigd/);
  assert.match(overlay, /document\.dispatchEvent\(new Event\("visibilitychange"\)\)/);
});

test("global Strategy 2 saves preserve existing pair overrides", () => {
  assert.match(settingsRoute, /preserveExistingPairOverrides/);
  assert.match(settingsRoute, /pairOverrides/);
  assert.match(settingsRoute, /\/api\/exchanges\/aster/);
  assert.match(settingsRoute, /hasOwnProperty\.call\(settingsRecord, "pairOverrides"\)/);
});
