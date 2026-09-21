import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const maker = readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

test("margin values are never converted into fixed position values", () => {
  assert.doesNotMatch(maker, /legacyLongMargin\s*\*\s*persistedMinLeverage/);
  assert.doesNotMatch(maker, /legacyShortMargin\s*\*\s*persistedMinLeverage/);
  assert.match(maker, /margin-mode entryNotionalUsd values were derived aliases, not user input/);
});

test("base LONG and SHORT margin controls remain visible and independent when fixed size is enabled", () => {
  assert.match(maker, /label="Instap LONG · margin"/);
  assert.match(maker, /label="Instap SHORT · margin"/);
  assert.match(maker, /v\.fixedPositionSize && <Field label="Vaste positie LONG"/);
  assert.match(maker, /v\.fixedPositionSize && <Field label="Vaste positie SHORT"/);
  assert.match(maker, /entryMarginLongUsd: longEntry/);
  assert.match(maker, /entryMarginShortUsd: shortEntry/);
});

test("margin mode preserves stored notionals instead of overwriting them with zero or derived values", () => {
  assert.match(maker, /const sizingSettings = v\.fixedPositionSize \? \{/);
  assert.match(maker, /entrySizingMode: "margin"/);
  assert.doesNotMatch(maker, /entrySizingMode: "margin",[\s\S]{0,180}entryNotionalLongUsd:/);
});

test("enabling fixed size requires explicit position values instead of leverage conversion", () => {
  assert.match(maker, /Vul Vaste positie LONG expliciet in/);
  assert.match(maker, /Vul Vaste positie SHORT expliciet in/);
  assert.match(maker, /wordt niet automatisch omgerekend/);
});

test("unrelated saves preserve fresh server sizing mode unless the user touched the switch", () => {
  assert.match(maker, /sizingModeTouched/);
  assert.match(maker, /withLatestProtectedSettings/);
  assert.match(maker, /!sizingModeTouched/);
  assert.match(maker, /latestSettings\.entrySizingMode/);
  assert.match(maker, /setSizingModeTouched\(true\)/);
  assert.match(maker, /savedSizing !== outgoingSizingMode/);
});
