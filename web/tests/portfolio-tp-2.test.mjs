import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const maker = readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const settingsRoute = readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts", import.meta.url), "utf8");
const resetRoute = readFileSync(new URL("../app/api/exchanges/aster/strategy2/portfolio-cycle/reset/route.ts", import.meta.url), "utf8");

test("Portfolio TP 2.0 uses the approved visual reference and obvious active tabs", () => {
  assert.match(maker, /file_00000000f6e08210b726c694adc15111/);
  assert.match(maker, /data-visual-reference=\{PORTFOLIO_TP_REFERENCE\}/);
  assert.match(maker, /tp-tabs button\.active\{[^}]*#e2ba4c[^}]*linear-gradient/);
  assert.match(maker, /aria-pressed=\{v\.tpMode === mode\}/);
});

test("Portfolio TP offers percent, dollar and all three base modes", () => {
  for (const token of [
    '"PERCENT"', '"USD"', '"CYCLE_START"', '"CURRENT_VALUE"', '"CUSTOM"',
    "TP invoermodus", "Bereken vanaf", "Cycle start", "Huidige waarde", "Aangepast",
    "Basiswaarde", "Doelwaarde", "Cycle start gereset",
  ]) assert.ok(maker.includes(token), token);
  assert.match(maker, /mode === "USD" \? base \+ value : base \* \(1 \+ value \/ 100\)/);
});

test("current-value preview snapshots the live equity instead of chasing target math", () => {
  assert.match(maker, /v\.portfolioTpBaseMode === "CURRENT_VALUE" \? currentEquity/);
  assert.match(maker, /portfolioTpBaseMode: v\.portfolioTpBaseMode/);
  assert.match(maker, /portfolioTpCustomBaseEquity: n\(v\.portfolioTpCustomBase\)/);
});

test("cycle reset calls the dedicated order-free server route", () => {
  assert.match(maker, /\/api\/exchanges\/aster\/strategy2\/portfolio-cycle\/reset/);
  assert.match(maker, /result\.ordersSent \?\? -1/);
  assert.match(resetRoute, /\/v1\/me\/aster\/strategy2\/portfolio-cycle\/reset/);
  assert.match(resetRoute, /"POST"/);
});

test("settings compatibility proxy preserves every Portfolio TP 2.0 field", () => {
  for (const key of [
    "portfolioTpPercent",
    "portfolioTpInputMode",
    "portfolioTpValue",
    "portfolioTpBaseMode",
    "portfolioTpCustomBaseEquity",
  ]) assert.ok(settingsRoute.includes(`"${key}"`), key);
});

test("display math matches product acceptance examples", () => {
  const target = (base, mode, value) => mode === "USD" ? base + value : base * (1 + value / 100);
  assert.equal(target(92.27, "PERCENT", 2).toFixed(2), "94.12");
  assert.equal(target(92.27, "PERCENT", 0.25).toFixed(2), "92.50");
  assert.equal(target(92.27, "USD", 5).toFixed(2), "97.27");
});
