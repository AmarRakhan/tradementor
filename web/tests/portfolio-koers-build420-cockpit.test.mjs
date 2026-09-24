import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("Build 420 keeps async zone advisor updates out of the chart creation dependency list", async () => {
  const source = await read("../components/portfolio-koers-chart.tsx");
  assert.match(source, /advisorZoneLadderRef=useRef<any>\(null\)/);
  assert.match(source, /activeZoneRef=useRef<number\|null>\(null\)/);
  assert.match(source, /useEffect\(\(\)=>\{syncOverlaysRef\.current\(\)\},\[advisorZoneLadder,activeZone\]\)/);
  assert.match(source, /\},\[baseCandles,payload\.markers,payload\.zones,payload\.cycleStartEquity,timeframe\]\);/);
  assert.doesNotMatch(source, /\},\[baseCandles,payload\.markers,payload\.zones,payload\.cycleStartEquity,timeframe,advisorZoneLadder,activeZone\]\);/);
});

test("Build 420 renders a compact Portfolio Snapshot-family strategy cockpit", async () => {
  const [source, css] = await Promise.all([
    read("../components/portfolio-koers-chart.tsx"),
    read("../app/portfolio-koers-chart.css"),
  ]);
  for (const token of [
    "portfolio-strategy-cockpit",
    "portfolio-strategy-action",
    "portfolio-strategy-grid",
    "ACTIEVE ZONE",
    "FORMATIE",
    "BALANS",
    "VOLGENDE ZONE",
    "BALANS NODIG",
  ]) assert.ok(source.includes(token), token);
  assert.ok(css.includes("--psc-gold:#e8b83d"));
  assert.ok(css.includes(".portfolio-koers-zones.is-ready"));
  assert.ok(css.includes("rgba(28,226,162,.085)"));
  assert.ok(source.includes("ZONEFORMATIE"));
  assert.ok(source.includes("IN ZONE OPEN"));
  assert.ok(source.includes("IN ZONE VRIJ"));
  assert.ok(source.includes("Oude zones nog open"));
  assert.ok(source.includes("Exposure:"));
});

test("generic exposure refill remains explicit, optional and capacity-neutral in zone mode", async () => {
  const [configurator, core] = await Promise.all([
    read("../components/aster-bot-configurator-v2.tsx"),
    read("../../cloud_api/aster_multi_bb_core.py"),
  ]);
  assert.ok(configurator.includes("settings.exposureRefillEnabled === true"));
  assert.ok(configurator.includes("Los van Zone-Soldaten"));
  assert.ok(configurator.includes("Maakt geen extra slots of soldaten en omzeilt zone-capaciteit niet."));
  assert.ok(configurator.includes("Wijziging wordt pas actief nadat je Opslaan kiest."));
  assert.ok(configurator.includes('exposureRuntimeLabel = !savedExposureRefillEnabled'));
  assert.ok(core.includes("exposure_refill_enabled: bool = False"));
  assert.ok(core.includes("if settings.exposure_refill_enabled and str(exposure.get(\"activeSide\") or \"\").upper() == normalized_side:"));
  assert.ok(core.includes('long_need = 0 if zone_migration_hold else len(available_soldiers(zone_state or {}, "LONG"))'));
  assert.ok(core.includes('short_need = 0 if zone_migration_hold else len(available_soldiers(zone_state or {}, "SHORT"))'));
});
