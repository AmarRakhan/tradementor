import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const bridge = readFileSync(new URL("../components/aster-profit-lock-ladder-bridge.tsx", import.meta.url), "utf8");
const card = readFileSync(new URL("../components/aster-bollinger-entry-filter-15m-card.tsx", import.meta.url), "utf8");

test("Bollinger entry filter reference and approved copy are present above Profit Lock", () => {
  assert.match(card, /file_00000000409081f49fd5473a5a7ee770/);
  assert.match(card, /Bollinger instapfilter 15m/);
  assert.match(card, /Open LONG alleen onder de onderste band en SHORT alleen boven de bovenste band\./);
  assert.match(card, /Live prijs vs 15m Bollinger Bands · optioneel/);
  const bb = bridge.indexOf("<AsterBollingerEntryFilter15mCard");
  const pll = bridge.indexOf("<AsterProfitLockLadderPanel");
  assert.ok(bb >= 0 && pll > bb, "Bollinger card must render immediately before Profit Lock Ladder");
});

test("toggle persists only explicit per-user boolean and defaults visually off", () => {
  assert.match(bridge, /bollingerEntryFilter15mEnabled === true/);
  assert.match(bridge, /bollingerEntryFilter15mEnabled: next/);
  assert.match(bridge, /useState\(false\)/);
});
