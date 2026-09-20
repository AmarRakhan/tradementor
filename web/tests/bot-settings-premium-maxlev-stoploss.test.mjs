import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const settingsRoute = fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts", import.meta.url), "utf8");
const tierRoute = fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/leverage-tiers/route.ts", import.meta.url), "utf8");
const bridge = fs.readFileSync(new URL("../components/aster-profit-lock-ladder-bridge.tsx", import.meta.url), "utf8");

test("Bot Settings uses the approved compact visual reference and one slot overview", () => {
  assert.ok(maker.includes("file_00000000d2ec81f4b0c6fe6b9befe97c"));
  assert.ok(maker.includes('className="slot-overview"'));
  assert.ok(maker.includes('className="slot-row long"'));
  assert.ok(maker.includes('className="slot-row short"'));
  assert.ok(maker.includes('className="slot-row total"'));
  assert.equal(maker.includes('className="strategy-facts"'), false);
  assert.equal(maker.includes('className="strategy-message compact-scan"'), false);
});

test("existing settings stay on their existing maker and compact SHORT-only control", () => {
  for (const label of [
    "Botnaam", "Top-N volume", "Totaal posities", "LONG slots", "SHORT slots",
    "Minimum leverage", "SHORT alleen met LONG", "Instap LONG", "Instap SHORT",
    "DCA-afstand LONG", "DCA-afstand SHORT", "DCA-bedrag LONG", "DCA-bedrag SHORT",
    "Max DCA LONG", "Max DCA SHORT", "Take Profit LONG", "Take Profit SHORT",
    "Smart Rescue DCA", "Zelf munten kiezen", "Instellingen opslaan",
    "Veilig simuleren", "Readiness controleren",
  ]) assert.ok(maker.includes(label), `missing existing control: ${label}`);
  assert.ok(maker.includes("short-pair-control"));
});

test("Maximum leverage is optional, validated and sent through tier preview", () => {
  assert.ok(maker.includes('label="Maximum leverage"'));
  assert.ok(maker.includes("maxLeverage.trim()"));
  assert.ok(maker.includes("maximumLeverage: maxLeverage"));
  assert.ok(maker.includes("Maximum leverage moet gelijk aan of hoger zijn dan Minimum leverage"));
  assert.ok(maker.includes("query.maximumLeverage"));
  assert.ok(tierRoute.includes("url.search"));
});

test("Stoploss has explicit off-by-default toggle, mode and separate side values", () => {
  assert.ok(maker.includes("stopLossEnabled: false"));
  assert.ok(maker.includes('stopLossMode: "PERCENT"'));
  assert.ok(maker.includes("Stoploss LONG"));
  assert.ok(maker.includes("Stoploss SHORT"));
  assert.ok(maker.includes('v.stopLossMode === "USD"'));
  assert.ok(maker.includes('role="switch" aria-checked={v.stopLossEnabled}'));
});

test("new fields survive saves from older or independent settings editors", () => {
  for (const key of ["maximumLeverage", "stopLossEnabled", "stopLossMode", "stopLossLong", "stopLossShort"]) {
    assert.ok(settingsRoute.includes(`"${key}"`), `missing preservation key: ${key}`);
  }
});

test("inactive Profit Lock does not add a permanent extra save row to compact layout", () => {
  assert.ok(bridge.includes('{(dirty || enabled) ? <div className="pll-save-row"'));
});

test("premium compact CSS covers slot bars, live config and Stoploss card", () => {
  assert.ok(maker.includes(".slot-overview{"));
  assert.ok(maker.includes(".slot-row>i u{"));
  assert.ok(maker.includes(".live-config-grid{"));
  assert.ok(maker.includes("grid-template-columns:2fr 1fr .9fr .75fr .75fr .95fr .95fr"));
  assert.ok(maker.includes(".stop-loss-card{"));
  assert.ok(maker.includes(".stop-loss-fields{"));
});

test("fixed position size is optional, explicit and persisted", () => {
  assert.ok(maker.includes("Vaste positieomvang"));
  assert.ok(maker.includes('role="switch" aria-checked={v.fixedPositionSize}'));
  assert.ok(maker.includes('entrySizingMode: v.fixedPositionSize ? "notional" : "margin"'));
  assert.ok(maker.includes("entryNotionalLongUsd: longNotional"));
  assert.ok(maker.includes("entryNotionalShortUsd: shortNotional"));
  assert.ok(maker.includes('"Instap LONG · positie"'));
  assert.ok(maker.includes('"Instap LONG · margin"'));
  assert.ok(maker.includes("margin = positie ÷ leverage"));
});

test("settings route preserves sizing mode and side notionals", () => {
  for (const key of ["entrySizingMode", "entryNotionalUsd", "entryNotionalLongUsd", "entryNotionalShortUsd"]) {
    assert.ok(settingsRoute.includes('"' + key + '"'), "missing sizing preservation key: " + key);
  }
});

test("confirmed save verifies maximum leverage and sizing mode before clearing dirty state", () => {
  assert.ok(maker.includes("Maximum leverage is niet server-side bevestigd"));
  assert.ok(maker.includes("Positieomvang-modus is niet server-side bevestigd"));
  assert.ok(maker.includes("setDirty(false)"));
});
