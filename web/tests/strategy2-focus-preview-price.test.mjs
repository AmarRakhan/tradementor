import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

test("Multi BB entry sizing keeps independent LONG and SHORT values with optional fixed position size", () => {
  assert.match(maker, /Instap LONG/);
  assert.match(maker, /Instap SHORT/);
  assert.match(maker, /fixedPositionSize:\s*false/);
  assert.match(maker, /entrySizingMode:\s*v\.fixedPositionSize \? "notional" : "margin"/);
  assert.match(maker, /entryMarginLongUsd:\s*longEntry/);
  assert.match(maker, /entryMarginShortUsd:\s*shortEntry/);
  assert.match(maker, /entryNotionalLongUsd:\s*longNotional/);
  assert.match(maker, /entryNotionalShortUsd:\s*shortNotional/);
  assert.match(maker, /DCA-bedrag LONG/);
  assert.match(maker, /DCA-bedrag SHORT/);
  assert.doesNotMatch(maker, /focusExposurePreview/);
});
