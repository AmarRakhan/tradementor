import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const shell = fs.readFileSync(new URL("../components/aster-strategy2-entry.tsx", import.meta.url), "utf8");
const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const backend = fs.readFileSync(new URL("../../cloud_api/main.py", import.meta.url), "utf8");

test("Build 544 removes the dual-mode Botinstellingen shell", () => {
  assert.match(shell, /return <AsterStrategy2Maker \{\.\.\.props\} \/>/);
  assert.doesNotMatch(shell, /BotSettingsMode|changeMode|Oude instellingen|Nieuwe configurator|ConfiguratorV3/);
});

test("the one live Botinstellingen surface contains canonical price-zone controls", () => {
  assert.match(maker, /Prijszone-stoelen/);
  assert.match(maker, /priceZoneSeats:\s*\{/);
  assert.match(maker, /longSeatsPerZone/);
  assert.match(maker, /shortSeatsPerZone/);
  assert.doesNotMatch(maker, /Warrior/i);
});

test("UI simplification does not remove existing user-scoped legacy preference data from backend", () => {
  assert.match(backend, /botSettingsUi/);
  assert.match(backend, /configurator3Enabled/);
});

test("single live surface still uses the existing Strategy 2 settings engine", () => {
  assert.match(maker, /\/api\/exchanges\/aster\/strategy2\/\$\{route\}/);
  assert.match(maker, /engine: "multi_bb_v1"/);
  assert.match(maker, /strategyKind: "multi_bb_v1"/);
});
