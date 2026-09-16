import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const bridge = readFileSync(new URL("../components/aster-profit-lock-ladder-bridge.tsx", import.meta.url), "utf8");
const card = readFileSync(new URL("../components/aster-bollinger-entry-filter-15m-card.tsx", import.meta.url), "utf8");

test("Bollinger timeframe UI matches approved contract and stays above Profit Lock", () => {
  assert.match(card, /file_00000000938481f4912fc885bdf10916/);
  assert.match(card, /<strong>Bollinger instapfilter<\/strong>/);
  assert.doesNotMatch(card, /<strong>Bollinger instapfilter 15m<\/strong>/);
  for (const label of ["1m", "5m", "15m", "1u", "4u", "1d"]) assert.match(card, new RegExp(`label: "${label}"`));
  assert.match(card, /value: "1h", label: "1u"/);
  assert.match(card, /value: "4h", label: "4u"/);
  assert.match(card, /grid-template-columns:repeat\(6,minmax\(0,1fr\)\)/);
  const bb = bridge.indexOf("<AsterBollingerEntryFilter15mCard");
  const pll = bridge.indexOf("<AsterProfitLockLadderPanel");
  assert.ok(bb >= 0 && pll > bb, "Bollinger card must render immediately before Profit Lock Ladder");
});

test("enabled state and selected timeframe persist independently with 15m default", () => {
  assert.match(bridge, /useState<BollingerEntryTimeframe>\("15m"\)/);
  assert.match(bridge, /bollingerEntryFilter15mEnabled === true/);
  assert.match(bridge, /bollingerEntryFilterTimeframe/);
  assert.match(bridge, /toggleBollingerEntryFilter/);
  assert.match(bridge, /changeBollingerTimeframe/);
  assert.match(bridge, /window\.dispatchEvent\(new Event\("aster-strategy2-settings-changed"\)\)/);
});
