import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const maker = readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../app/strategy2-reference.css", import.meta.url), "utf8");

test("Botinstellingen keeps real controls and adds persistent TP toggle", () => {
  for (const text of ["Aster live bot", "Instellingen opslaan", "Veilig simuleren", "Readiness controleren", "Zelf munten kiezen"]) assert.match(maker, new RegExp(text));
  assert.match(maker, /takeProfitEnabled: v\.tpEnabled/);
  assert.match(maker, /x\.takeProfitEnabled !== false/);
  assert.match(maker, /role="switch" aria-checked=\{v\.tpEnabled\}/);
  assert.match(maker, /disabled=\{!v\.tpEnabled\}/);
});

test("Botinstellingen reference styling is compact mobile-safe dark green and gold", () => {
  assert.match(css, /Botinstellingen definitive dark-green\/gold reference 2026-09-03/);
  assert.match(css, /#strategy-2-maker \.compact-settings-grid/);
  assert.match(css, /safe-area-inset-bottom/);
  assert.match(css, /@media \(max-width: 430px\)/);
});
