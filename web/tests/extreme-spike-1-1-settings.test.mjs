// Extreme Spike 1.1: instellingen-contract tussen app en backend (besluiten Amar 22-10-2026).
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  normalizeSpikeLevel, sameSpikeConfig, spikeConfigFromSettings, spikeSettingsPayload, spikeValidationError,
} from "../lib/extreme-spike-settings.mjs";

test("standaard: OFF, niveau 20,5, 15m, LONG aan, SHORT uit, TP 1%, trailing uit", () => {
  const config = spikeConfigFromSettings({});
  assert.equal(config.mode, "OFF");
  assert.equal(config.level, "5");
  assert.equal(config.long.timeframe, "15m");
  assert.equal(config.short.timeframe, "15m");
  assert.equal(config.long.enabled, true);
  assert.equal(config.short.enabled, false);
  assert.equal(config.long.takeProfitPct, 1);
  assert.equal(config.long.trailingEnabled, false);
});

test("Bollinger-schakelaar wint; een 1.0-record zet Spike niet aan", () => {
  assert.equal(spikeConfigFromSettings({ bollingerEntryFilter15mEnabled: true, entryFilterMode: "EXTREME_SPIKE", extremeSpikeSettingsVersion: 2 }).mode, "BOLLINGER");
  assert.equal(spikeConfigFromSettings({ entryFilterMode: "EXTREME_SPIKE", extremeSpikeLevel: "5-6" }).mode, "OFF");
  assert.equal(spikeConfigFromSettings({ entryFilterMode: "EXTREME_SPIKE", extremeSpikeSettingsVersion: 2 }).mode, "EXTREME_SPIKE");
});

test("niveaus zijn 'vanaf'; oude vensters worden hun ondergrens", () => {
  assert.equal(normalizeSpikeLevel("5-6"), "5");
  assert.equal(normalizeSpikeLevel("7+"), "7");
  assert.equal(normalizeSpikeLevel("6"), "6");
  assert.equal(normalizeSpikeLevel("onzin"), "5");
});

test("payload heeft dezelfde veldnamen als de backend en rondt terug", () => {
  const config = {
    mode: "EXTREME_SPIKE", level: "6",
    long: { enabled: true, timeframe: "15m", takeProfitPct: 0.5, trailingEnabled: true, trailingPct: 0.2, minDistancePct: 2.5 },
    short: { enabled: true, timeframe: "1m", takeProfitPct: 2, trailingEnabled: false, trailingPct: 0.3, minDistancePct: 0 },
  };
  const payload = spikeSettingsPayload(config);
  assert.equal(payload.entryFilterMode, "EXTREME_SPIKE");
  assert.equal(payload.bollingerEntryFilter15mEnabled, false);
  assert.equal(payload.extremeSpikeSettingsVersion, 2);
  assert.equal(payload.extremeSpikeShortTakeProfitPct, 2);
  assert.equal(payload.extremeSpikeLongTrailingPct, 0.2);
  assert.equal(payload.extremeSpikeLongMinDistancePct, 2.5);
  assert.equal(payload.extremeSpikeShortMinDistancePct, 0);
  assert.ok(sameSpikeConfig(spikeConfigFromSettings(payload), config));
});

test("validatie: TP minimaal 0,1%, trailing kleiner dan TP", () => {
  const base = spikeConfigFromSettings({ entryFilterMode: "EXTREME_SPIKE", extremeSpikeSettingsVersion: 2 });
  assert.equal(spikeValidationError(base), "");
  assert.notEqual(spikeValidationError({ ...base, long: { ...base.long, takeProfitPct: 0.05 } }), "");
  assert.equal(spikeValidationError({ ...base, long: { ...base.long, takeProfitPct: 0.1 } }), "");
  assert.notEqual(spikeValidationError({ ...base, short: { ...base.short, trailingEnabled: true, takeProfitPct: 0.5, trailingPct: 0.5 } }), "");
  assert.equal(spikeValidationError({ ...base, short: { ...base.short, trailingEnabled: true, takeProfitPct: 1, trailingPct: 0.3 } }), "");
});

test("kaart en opslaan zijn aangesloten; route bewaart de Spike-velden", async () => {
  const [card, bridge, route] = await Promise.all([
    readFile(new URL("../components/aster-extreme-spike-entry-card.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-profit-lock-ladder-bridge.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts", import.meta.url), "utf8"),
  ]);
  assert.match(card, /spike-side-/);
  assert.match(card, /Trailing/);
  assert.match(card, /20,\{draft\.level\}/);
  assert.match(bridge, /AsterExtremeSpikeEntryCard config=\{spikeConfig\}/);
  assert.match(bridge, /readbackSnapshot/);
  for (const key of ["extremeSpikeSettingsVersion", "extremeSpikeLongTakeProfitPct", "extremeSpikeShortTrailingPct", "extremeSpikeShortEnabled"]) {
    assert.ok(route.includes(`"${key}"`), key);
  }
  assert.doesNotMatch(route, /status:409/);
});

test("gekozen tijdframe licht op (Amar 23-10 00:32, build 612)", async () => {
  const card = await readFile(new URL("../components/aster-extreme-spike-entry-card.tsx", import.meta.url), "utf8");
  assert.match(card, /className=\{value\.timeframe === tf \? "selected" : ""\}/);
  assert.match(card, /value\.timeframe === tf \? "✓ " : ""/);
  // De oplicht-regel staat NA de basisregel en is een volle groene vulling, niet donkergroen op donkergroen.
  const base = card.indexOf(".es-timeframe button{");
  const lit = card.indexOf(".extreme-entry-card .es-timeframe button.selected");
  assert.ok(base > 0 && lit > base, "oplicht-regel na basisregel");
  assert.match(card.slice(lit, lit + 260), /background:#0af291!important/);
});

test("Instapfilter springt niet terug bij elke refresh (Amar 23-10 00:43, build 613)", async () => {
  const card = await readFile(new URL("../components/aster-extreme-spike-entry-card.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(card, /useEffect\(\(\) => \{ setDraft\(config\); \}, \[config\]\)/);
  assert.match(card, /const configKey = JSON\.stringify\(config\)/);
  assert.match(card, /if \(previous === configKey\) return;/);
  assert.match(card, /currentKey === previous \|\| currentKey === configKey \? config : current/);
});

test("terug naar Bollinger/Geen filter slaat direct op (Amar 23-10 01:28, build 615)", async () => {
  const [card, bridge] = await Promise.all([
    readFile(new URL("../components/aster-extreme-spike-entry-card.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-profit-lock-ladder-bridge.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(card, /onClick=\{\(\) => selectMode\(mode\)\}/);
  assert.match(card, /if \(mode !== "EXTREME_SPIKE" && mode !== config\.mode\) onSave\(next\);/);
  // De Bollinger-kaart volgt de opgeslagen modus; die wordt nu direct BOLLINGER.
  assert.match(bridge, /entryMode === "BOLLINGER" \? <AsterBollingerEntryFilter15mCard/);
  // Opslaan als BOLLINGER zet de bestaande Bollinger-schakelaar aan.
  const { spikeSettingsPayload, spikeConfigFromSettings } = await import("../lib/extreme-spike-settings.mjs");
  const fromSpike = spikeConfigFromSettings({ entryFilterMode: "EXTREME_SPIKE", extremeSpikeSettingsVersion: 2 });
  const payload = spikeSettingsPayload({ ...fromSpike, mode: "BOLLINGER" });
  assert.equal(payload.entryFilterMode, "BOLLINGER");
  assert.equal(payload.bollingerEntryFilter15mEnabled, true);
  assert.equal(spikeConfigFromSettings(payload).mode, "BOLLINGER");
});

test("build 624: minimale afstand per kant, aanbevolen 2%, 0 = uit, max 20%, met uitleg", async () => {
  const config = spikeConfigFromSettings({ entryFilterMode: "EXTREME_SPIKE", extremeSpikeSettingsVersion: 2 });
  assert.equal(config.long.minDistancePct, 2);
  assert.equal(config.short.minDistancePct, 2);
  assert.equal(spikeValidationError({ ...config, long: { ...config.long, minDistancePct: 0 } }), "");
  assert.notEqual(spikeValidationError({ ...config, long: { ...config.long, minDistancePct: 25 } }), "");
  assert.notEqual(spikeValidationError({ ...config, short: { ...config.short, minDistancePct: -1 } }), "");
  const [card, route] = await Promise.all([
    readFile(new URL("../components/aster-extreme-spike-entry-card.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/strategy2/settings/route.ts", import.meta.url), "utf8"),
  ]);
  assert.match(card, /Minimale afstand tot het gemiddelde/);
  assert.match(card, /aanbevolen \{SPIKE_MIN_DISTANCE_RECOMMENDED\}%/);
  assert.match(card, /geen spike/);
  for (const key of ["extremeSpikeLongMinDistancePct", "extremeSpikeShortMinDistancePct"]) assert.ok(route.includes(`"${key}"`), key);
});
