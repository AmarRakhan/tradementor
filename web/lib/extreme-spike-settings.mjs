// Extreme Spike 1.1 — instellingen lezen, schrijven en valideren (zelfde regels als de backend:
// cloud_api/aster_extreme_spike_filter.py spike_settings_from_mapping / validate_side_settings /
// effective_entry_filter_mode).
export const SPIKE_LEVELS = ["2", "3", "4", "5", "6", "7"];
export const SPIKE_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];
export const SPIKE_TP_MIN = 0.1;
export const SPIKE_TP_MAX = 50;
const LEGACY_LEVELS = { "2-3": "2", "3-4": "3", "4-5": "4", "5-6": "5", "6-7": "6", "7+": "7" };

function frame(value) {
  const text = String(value ?? "");
  return SPIKE_TIMEFRAMES.includes(text) ? text : "15m";
}
function pct(value, fallback) {
  const number = typeof value === "number" ? value : Number(value);
  return value !== null && value !== "" && Number.isFinite(number) ? number : fallback;
}
export function normalizeSpikeLevel(value) {
  const text = String(value ?? "").trim().replace(/\.0$/, "");
  if (SPIKE_LEVELS.includes(text)) return text;
  return LEGACY_LEVELS[text] ?? "5";
}

export function spikeConfigFromSettings(settings) {
  const record = settings && typeof settings === "object" ? settings : {};
  const bollinger = record.bollingerEntryFilter15mEnabled === true;
  const spikeSaved = record.entryFilterMode === "EXTREME_SPIKE" && Number(record.extremeSpikeSettingsVersion) === 2;
  const side = (prefix, defaultEnabled) => ({
    enabled: record[`extremeSpike${prefix}Enabled`] === undefined ? defaultEnabled : record[`extremeSpike${prefix}Enabled`] === true,
    timeframe: frame(record[`extremeSpike${prefix}Timeframe`]),
    takeProfitPct: pct(record[`extremeSpike${prefix}TakeProfitPct`], 1),
    trailingEnabled: record[`extremeSpike${prefix}TrailingEnabled`] === true,
    trailingPct: pct(record[`extremeSpike${prefix}TrailingPct`], 0.3),
  });
  return {
    mode: bollinger ? "BOLLINGER" : spikeSaved ? "EXTREME_SPIKE" : "OFF",
    level: normalizeSpikeLevel(record.extremeSpikeLevel),
    long: side("Long", true),
    short: side("Short", false),
  };
}

export function spikeSettingsPayload(config) {
  const side = (prefix, value) => ({
    [`extremeSpike${prefix}Enabled`]: value.enabled,
    [`extremeSpike${prefix}Timeframe`]: value.timeframe,
    [`extremeSpike${prefix}TakeProfitPct`]: value.takeProfitPct,
    [`extremeSpike${prefix}TrailingEnabled`]: value.trailingEnabled,
    [`extremeSpike${prefix}TrailingPct`]: value.trailingPct,
  });
  return {
    entryFilterMode: config.mode,
    bollingerEntryFilter15mEnabled: config.mode === "BOLLINGER",
    extremeSpikeSettingsVersion: 2,
    extremeSpikeLevel: config.level,
    ...side("Long", config.long),
    ...side("Short", config.short),
  };
}

export function spikeValidationError(config) {
  if (config.mode !== "EXTREME_SPIKE") return "";
  for (const [label, side] of [["LONG", config.long], ["SHORT", config.short]]) {
    if (!(side.takeProfitPct >= SPIKE_TP_MIN && side.takeProfitPct <= SPIKE_TP_MAX)) return `${label}: Spike-TP moet tussen ${SPIKE_TP_MIN}% en ${SPIKE_TP_MAX}% liggen.`;
    if (side.trailingEnabled && !(side.trailingPct > 0 && side.trailingPct < side.takeProfitPct)) return `${label}: trailing-terugval moet groter dan 0 en kleiner dan de Spike-TP zijn.`;
  }
  return "";
}

export function sameSpikeConfig(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}
