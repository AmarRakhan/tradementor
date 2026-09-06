import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const maker = readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

test("Botinstellingen keeps real controls and three mutually exclusive TP modes inline", () => {
  for (const text of ["Aster live bot", "Instellingen opslaan", "Veilig simuleren", "Readiness controleren", "Zelf munten kiezen", "Per trade", "Portfolio", "Uit"]) assert.match(maker, new RegExp(text));
  assert.match(maker, /takeProfitMode:\s*v\.tpMode/);
  assert.match(maker, /takeProfitEnabled:\s*v\.tpMode === "PER_TRADE"/);
  assert.match(maker, /disabled=\{v\.tpMode !== "PER_TRADE"\}/);
});

test("Botinstellingen reference styling is compact mobile-safe dark green and gold", () => {
  assert.match(maker, /--gold:#d6b55a/);
  assert.match(maker, /--green:#21d69a/);
  assert.match(maker, /safe-area-inset-bottom/);
  assert.match(maker, /@media\(max-width:430px\)/);
  assert.match(maker, /grid-template-columns:1fr 1fr/);
});
