import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const css = fs.readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");

test("manual symbol selection remains opt-in inside the direct settings panel", () => {
  assert.match(maker, /manualEnabled:\s*false/);
  assert.match(maker, /Zelf munten kiezen/);
  assert.match(maker, /UIT = automatische Top-N/);
  assert.match(maker, /manualSymbolSelectionEnabled:\s*v\.asymmetricHedgeEnabled \? false : v\.manualEnabled/);
  assert.match(maker, /Geen wizard/);
});

test("manual picker loads real Aster markets and stores explicit LONG SHORT sides", () => {
  assert.match(maker, /strategy2\/focus\/markets/);
  assert.match(maker, /manualSymbols:\s*v\.manualSymbols/);
  assert.match(maker, /setSymbolSide/);
  assert.match(maker, /"LONG"/);
  assert.match(maker, /"SHORT"/);
  assert.doesNotMatch(maker, /\[\s*\{\s*symbol:\s*"BTCUSDT"/);
});

test("manual picker remains removable and responsive without position-close side effects", () => {
  assert.match(maker, /removeSymbol/);
  assert.match(maker, /Geen actieve Aster USDT perpetual gevonden/);
  assert.match(css, /\.manual-symbol-mode/);
  assert.match(css, /@media\(max-width:640px\).*manual-symbol-search/s);
  assert.doesNotMatch(maker, /positions\/.*close/);
});
