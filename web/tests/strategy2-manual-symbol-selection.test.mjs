import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
const maker=fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
const css=fs.readFileSync(new URL("../app/globals.css",import.meta.url),"utf8");

test("manual symbol selection is optional and defaults off",()=>{
  assert.match(maker,/manualEnabled:\s*false/);
  assert.match(maker,/Zelf munten kiezen/);
  assert.match(maker,/UIT = exact huidige Top-N werking/);
  assert.match(maker,/manualSymbolSelectionEnabled:\s*v\.manualEnabled/);
});

test("manual picker loads real Aster markets and stores explicit LONG SHORT sides",()=>{
  assert.match(maker,/strategy2\/focus\/markets/);
  assert.match(maker,/manualSymbols:\s*v\.manualSymbols/);
  assert.match(maker,/setSymbolSide/);
  assert.match(maker,/"LONG"/);
  assert.match(maker,/"SHORT"/);
  assert.doesNotMatch(maker,/\[\s*\{\s*symbol:\s*"BTCUSDT"/);
});

test("manual picker is responsive and removable without closing positions",()=>{
  assert.match(maker,/removeSymbol/);
  assert.match(maker,/Bestaande posities worden nooit gesloten door deze keuze/);
  assert.match(css,/\.manual-symbol-mode/);
  assert.match(css,/@media\(max-width:640px\).*manual-symbol-search/s);
});
