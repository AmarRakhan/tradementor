import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const source = fs.readFileSync(new URL("../components/aster-bot-configurator-v3.tsx", import.meta.url), "utf8");

test("Botconfigurator V3 exposes one AsterBot and price-zone seats as an option", () => {
  assert.match(source, /title="AsterBot"/);
  assert.match(source, /Eén bot, één beslispipeline/);
  assert.match(source, /label="Prijszone-stoelen"/);
  assert.doesNotMatch(source, /<strong>Zone Warriors<\/strong>/);
  assert.doesNotMatch(source, /<strong>Classic DCA<\/strong>/);
});

test("price-zone module is written through one canonical object plus migration aliases", () => {
  assert.match(source, /priceZoneSeats:\s*\{/);
  assert.match(source, /enabled: source\.zoneSoldiersEnabled/);
  assert.match(source, /longSeatsPerZone: sourceZoneLongSeats/);
  assert.match(source, /shortSeatsPerZone: sourceZoneShortSeats/);
  assert.match(source, /zoneSoldiersEnabled: source\.zoneSoldiersEnabled/);
});

test("normal accounts default to price-zone module disabled without automatic actions", () => {
  assert.match(source, /priceZoneSeats: \{ enabled: false, longSeatsPerZone: 0, shortSeatsPerZone: 0 \}/);
  const saveStart = source.indexOf("async function saveQuickEdit()");
  const saveEnd = source.indexOf("const strategyName =", saveStart);
  const save = source.slice(saveStart, saveEnd);
  assert.doesNotMatch(save, /strategy2\/start/);
  assert.doesNotMatch(save, /strategy2\/stop/);
  assert.doesNotMatch(save, /close/i);
});
