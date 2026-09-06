import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const legacyPopup = fs.readFileSync(new URL("../components/aster-side-tp-settings.tsx", import.meta.url), "utf8");

test("Botinstellingen is one inline mobile page without side-settings popup", () => {
  for (const text of [
    "Botinstellingen",
    "Aster live bot",
    "Instap LONG",
    "Instap SHORT",
    "LONG / SHORT · DCA & Take Profit",
    "Per trade",
    "Portfolio",
    "Uit",
    "Zelf munten kiezen",
    "Instellingen opslaan",
    "Veilig simuleren",
    "Readiness controleren",
  ]) assert.match(maker, new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.doesNotMatch(maker, /Asymmetrische short-hedge modus/);
  assert.doesNotMatch(maker, /Gekoppelde paren/);
  assert.doesNotMatch(maker, /Short start-multiplier/);
  assert.match(legacyPopup, /return null/);
  assert.doesNotMatch(legacyPopup, /role="dialog"/);
});

test("LONG and SHORT entry amounts persist independently with legacy fallback aliases", () => {
  assert.match(maker, /entryMarginLongUsd:\s*longEntry/);
  assert.match(maker, /entryMarginShortUsd:\s*shortEntry/);
  assert.match(maker, /entryMarginUsd:\s*longEntry/);
  assert.match(maker, /x\.entryMarginLongUsd \?\? x\.entryMarginLong \?\? legacyEntry/);
  assert.match(maker, /x\.entryMarginShortUsd \?\? x\.entryMarginShort \?\? legacyEntry/);
});

test("side-specific DCA and TP values do not collapse to one shared field", () => {
  assert.match(maker, /longDcaDistance:\s*longDistance/);
  assert.match(maker, /shortDcaDistance:\s*shortDistance/);
  assert.match(maker, /longDcaMarginUsd:\s*longAmount/);
  assert.match(maker, /shortDcaMarginUsd:\s*shortAmount/);
  assert.match(maker, /maxDcaLong:\s*maxLong/);
  assert.match(maker, /maxDcaShort:\s*maxShort/);
  assert.match(maker, /longTakeProfitValue:\s*longTp/);
  assert.match(maker, /shortTakeProfitValue:\s*shortTp/);
});

test("Portfolio and OFF modes preserve DCA while disabling individual TP execution", () => {
  assert.match(maker, /takeProfitMode:\s*v\.tpMode/);
  assert.match(maker, /takeProfitEnabled:\s*v\.tpMode === "PER_TRADE"/);
  assert.match(maker, /Automatische TP uit\. DCA en overige strategie blijven actief/);
});
