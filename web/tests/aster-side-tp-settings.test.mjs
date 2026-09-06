import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const ui = fs.readFileSync(new URL("../components/aster-side-tp-settings.tsx", import.meta.url), "utf8");
const layout = fs.readFileSync(new URL("../app/layout.tsx", import.meta.url), "utf8");

test("global settings expose exactly three mutually exclusive TP modes", () => {
  for (const value of ["PER_TRADE", "PORTFOLIO", "OFF"]) assert.ok(ui.includes(`"${value}"`));
  assert.match(ui, /mode === "PER_TRADE" \? "Per trade"/);
  assert.match(ui, /mode === "PORTFOLIO" \? "Portfolio"/);
  assert.match(ui, /: "Uit"/);
  assert.match(layout, /<AsterSideTpSettings \/>/);
});

test("LONG and SHORT settings are persisted independently", () => {
  for (const key of [
    "longDcaDistance", "shortDcaDistance",
    "longDcaMarginUsd", "shortDcaMarginUsd",
    "maxDcaLong", "maxDcaShort",
    "longTakeProfitValue", "shortTakeProfitValue",
  ]) assert.ok(ui.includes(key), `missing ${key}`);
});

test("portfolio UI uses immutable cycle baseline and real current equity presentation", () => {
  assert.match(ui, /cycleStartEquity/);
  assert.match(ui, /currentEquity/);
  assert.match(ui, /targetEquity/);
  assert.match(ui, /Cycle Start/);
  assert.match(ui, /Portfolio Target/);
  assert.match(ui, /Current Equity/);
  assert.match(ui, /Afstand/);
  assert.match(ui, /Cycle status/);
});

test("portfolio mode warns before saving when current equity already meets target", () => {
  assert.match(ui, /currentEquity >= selectedTarget/);
  assert.match(ui, /De huidige portfolio-equity ligt al boven het ingestelde target\. Na opslaan kan direct een volledige portfolio-exit starten\./);
});

test("individual LONG SHORT TP remains stored but visibly inactive in PORTFOLIO or OFF", () => {
  assert.match(ui, /disabled=\{!individualActive\}/);
  assert.match(ui, /const individualActive = draft\.mode === "PER_TRADE"/);
  assert.match(ui, /Niet actief in/);
  assert.match(ui, /Automatische Take Profit uitgeschakeld/);
});

test("legacy shared controls are hidden rather than becoming a second live settings source", () => {
  assert.match(ui, /DCA afstand/);
  assert.match(ui, /DCA margin/);
  assert.match(ui, /Globale DCA-limiet/);
  assert.match(ui, /\.tp-setting/);
  assert.match(ui, /LONG \/ SHORT · DCA & TAKE PROFIT INSTELLEN/);
});

test("saving modes does not request any active-state reset", () => {
  assert.match(ui, /Actieve posities en DCA-counts zijn niet gereset/);
  assert.doesNotMatch(ui, /resetCycle|resetDca|closeAll/);
});
