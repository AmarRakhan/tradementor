import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

test("direct settings cap the Aster bot at 25 LONG plus 25 SHORT and 50 total", () => {
  assert.match(maker, /Totaal posities/);
  assert.match(maker, /LONG slots/);
  assert.match(maker, /SHORT slots/);
  assert.match(maker, /maximumPositions:\s*Math\.min\(50, longSlots \+ shortSlots\)/);
  assert.match(maker, /const longSlots = clampInt\(n\(v\.longSlots\), 0, 25\)/);
  assert.match(maker, /const shortSlots = clampInt\(n\(v\.shortSlots\), 0, 25\)/);
  assert.match(maker, /entrySizingMode: "margin"/);
  assert.match(maker, /entryMarginLongUsd/);
  assert.match(maker, /entryMarginShortUsd/);
  assert.match(maker, /rawReport\.remainingLong/);
  assert.match(maker, /rawReport\.remainingShort/);
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
