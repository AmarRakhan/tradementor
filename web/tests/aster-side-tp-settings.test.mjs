import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const retired = fs.readFileSync(new URL("../components/aster-side-tp-settings.tsx", import.meta.url), "utf8");
const layout = fs.readFileSync(new URL("../app/layout.tsx", import.meta.url), "utf8");

test("global settings expose exactly three mutually exclusive TP modes inline", () => {
  for (const value of ["PER_TRADE", "PORTFOLIO", "OFF"]) assert.ok(maker.includes(`"${value}"`));
  assert.match(maker, /mode === "PER_TRADE" \? "Per trade"/);
  assert.match(maker, /mode === "PORTFOLIO" \? "Portfolio"/);
  assert.match(maker, /: "Uit"/);
  assert.match(layout, /<AsterSideTpSettings \/>/);
  assert.match(retired, /return null/);
});

test("LONG and SHORT settings are persisted independently on the main page", () => {
  for (const key of [
    "entryMarginLongUsd", "entryMarginShortUsd",
    "longDcaDistance", "shortDcaDistance",
    "longDcaMarginUsd", "shortDcaMarginUsd",
    "maxDcaLong", "maxDcaShort",
    "longTakeProfitValue", "shortTakeProfitValue",
  ]) assert.ok(maker.includes(key), `missing ${key}`);
});

test("portfolio UI presents existing immutable cycle values without reset controls", () => {
  assert.match(maker, /cycleStartEquity/);
  assert.match(maker, /currentEquity/);
  assert.match(maker, /targetEquity/);
  assert.match(maker, /Cycle start/);
  assert.match(maker, /Target/);
  assert.match(maker, /Equity/);
  assert.doesNotMatch(maker, /resetCycle|resetDca|closeAll/);
});

test("portfolio mode warns before saving when current equity already meets target", () => {
  assert.match(maker, /currentEquity >= target/);
  assert.match(maker, /na opslaan kan de bestaande Portfolio TP-cycle direct uitvoeren/i);
});

test("individual LONG SHORT TP stays stored but is visibly inactive in PORTFOLIO or OFF", () => {
  assert.match(maker, /disabled=\{v\.tpMode !== "PER_TRADE"\}/);
  assert.match(maker, /Automatische TP uit\. DCA en overige strategie blijven actief\./);
});

test("no legacy popup or duplicate DCA TP settings source remains", () => {
  assert.doesNotMatch(retired, /role="dialog"/);
  assert.doesNotMatch(retired, /LONG \/ SHORT · DCA & TAKE PROFIT INSTELLEN/);
  assert.match(maker, /LONG \/ SHORT · DCA & Take Profit/);
});

test("saving settings states that active trading state is preserved", () => {
  assert.match(maker, /Actieve posities, fills, avg entry, DCA-counts en Portfolio TP-cycle zijn intact gebleven/);
  assert.doesNotMatch(maker, /resetCycle|resetDca|closeAll/);
});
