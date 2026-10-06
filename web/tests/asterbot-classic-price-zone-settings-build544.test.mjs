import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const entry = fs.readFileSync(new URL("../components/aster-strategy2-entry.tsx", import.meta.url), "utf8");
const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

test("Botinstellingen uses one classic AsterBot surface without dual-mode tabs", () => {
  assert.match(entry, /<AsterStrategy2Maker \{\.\.\.props\} \/>/);
  assert.doesNotMatch(entry, /Nieuwe configurator/);
  assert.doesNotMatch(entry, /Oude instellingen/);
  assert.doesNotMatch(entry, /configurator3/);
});

test("classic AsterBot settings contains price-zone seats without Warrior branding", () => {
  assert.match(maker, /Prijszone-stoelen/);
  assert.match(maker, /LONG per prijszone/);
  assert.match(maker, /SHORT per prijszone/);
  assert.doesNotMatch(maker, /Warrior/i);
});

test("price-zone seats save through the canonical object and allow zero on one side", () => {
  assert.match(maker, /priceZoneSeats:\s*\{/);
  assert.match(maker, /longSeatsPerZone: clampInt\(n\(v\.priceZoneLongSeats\), 0, 100\)/);
  assert.match(maker, /shortSeatsPerZone: clampInt\(n\(v\.priceZoneShortSeats\), 0, 100\)/);
  assert.match(maker, /zoneLong \+ zoneShort < 1/);
});

test("global max is independent while price-zone seats are enabled", () => {
  assert.match(maker, /maximumPositions: v\.priceZoneSeatsEnabled/);
  assert.match(maker, /change\(\{ \.\.\.v, positions: String\(clampInt\(n\(raw\), 1, MAX_TOTAL_POSITIONS\)\) \}\)/);
});
