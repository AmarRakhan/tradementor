import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

test("direct settings cap the Aster bot at 25 LONG plus 25 SHORT and 50 total", () => {
  assert.match(maker, /Totaal posities \(max 50\)/);
  assert.match(maker, /LONG slots \(max 25\)/);
  assert.match(maker, /SHORT slots \(max 25\)/);
  assert.match(maker, /maximumPositions:\s*Math\.min\(50, longSlots \+ shortSlots\)/);
  assert.match(maker, /longSlots = clampInt\(n\(v\.longSlots\), 0, 25\)/);
  assert.match(maker, /shortSlots = clampInt\(n\(v\.shortSlots\), 0, 25\)/);
});

test("DCA remains percentage-gated with a hard global max of three and clean restart", () => {
  assert.match(maker, /dcaDistance:\s*n\(v\.dcaDistance\) \/ 100/);
  assert.match(maker, /maxDca:\s*clampInt\(n\(v\.maxDca\), 0, 3\)/);
  assert.match(maker, /entryMode:\s*"immediate_fill"/);
  assert.match(maker, /autoRestart:\s*true/);
  assert.match(maker, /marginMode:\s*"cross"/);
});

test("maker remains direct and contains no Bollinger or indicator entry gate", () => {
  assert.match(maker, /Alle actieve instellingen staan direct hieronder\. Geen wizard/);
  assert.match(maker, /Veilig simuleren/);
  assert.doesNotMatch(maker, /bollinger/i);
  assert.doesNotMatch(maker, /indicator.*gate/i);
});
