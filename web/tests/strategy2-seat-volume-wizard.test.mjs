import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

test("direct settings expose global max plus independent per-zone LONG and SHORT caps", () => {
  assert.match(maker, /Totaal posities/);
  assert.match(maker, /Prijszone-stoelen/);
  assert.match(maker, /LONG per prijszone/);
  assert.match(maker, /SHORT per prijszone/);
  assert.match(maker, /maximumPositions: v\.priceZoneSeatsEnabled/);
  assert.match(maker, /clampInt\(n\(v\.positions\), 1, MAX_TOTAL_POSITIONS\)/);
  assert.match(maker, /longSeatsPerZone: clampInt\(n\(v\.priceZoneLongSeats\), 0, 100\)/);
  assert.match(maker, /shortSeatsPerZone: clampInt\(n\(v\.priceZoneShortSeats\), 0, 100\)/);
  assert.match(maker, /zoneLong \+ zoneShort < 1/);
});

test("classic slots remain available when price-zone seats are off", () => {
  assert.match(maker, /LONG slots/);
  assert.match(maker, /SHORT slots/);
  assert.match(maker, /Math\.min\(MAX_TOTAL_POSITIONS, longSlots \+ shortSlots\)/);
  assert.match(maker, /const longSlots = clampInt\(n\(v\.longSlots\), 0, MAX_SIDE_SLOTS\)/);
  assert.match(maker, /const shortSlots = clampInt\(n\(v\.shortSlots\), 0, MAX_SIDE_SLOTS\)/);
});

test("DCA remains percentage-gated with editable independent limits and clean restart", () => {
  assert.match(maker, /longDcaDistance:\s*longDistance/);
  assert.match(maker, /shortDcaDistance:\s*shortDistance/);
  assert.match(maker, /maxDcaLong:\s*maxLong/);
  assert.match(maker, /maxDcaShort:\s*maxShort/);
  assert.match(maker, /entryMode:\s*"immediate_fill"/);
  assert.match(maker, /autoRestart:\s*true/);
  assert.match(maker, /marginMode:\s*"cross"/);
});

test("maker remains direct and contains no Bollinger or indicator entry gate", () => {
  assert.match(maker, /Veilig simuleren/);
  assert.match(maker, /LONG \/ SHORT · DCA & Take Profit/);
  assert.doesNotMatch(maker, /bollinger/i);
  assert.doesNotMatch(maker, /indicator.*gate/i);
});
