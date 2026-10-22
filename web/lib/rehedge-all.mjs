// Re-Hedge All 1.0 — pure presentation helpers (no trading logic; the server decides every size).

export const RECOVERY_STATUSES = ["RECOVERY", "REHEDGE_ARMED", "DISABLED", "MANUAL_RELEASE_PENDING", "MANUAL_RELEASE_UNCERTAIN"];

export function recoveryPairs(pairs) {
  return (Array.isArray(pairs) ? pairs : []).filter((pair) =>
    RECOVERY_STATUSES.includes(String(pair?.status || "").toUpperCase()),
  );
}

const OUTCOME_LABELS = {
  PROTECTED: "Volledig beschermd",
  PARTIAL: "Gedeeltelijk beschermd",
  PENDING: "Order wordt nog verwerkt",
  QUEUED: "Wordt binnen enkele seconden door Auto Hedge afgemaakt",
  TOO_SMALL: "Aanvulling te klein voor een Aster-order · hedget mee bij de volgende DCA",
  NO_MARGIN: "Onvoldoende margin",
  FAILED: "Mislukt",
  UNKNOWN: "Uitkomst onbekend · Auto Hedge controleert dezelfde order bij Aster, nooit dubbel",
  SKIPPED: "Overgeslagen",
  TEST_ONLY: "Testmodus · geen order",
};

const REASON_LABELS = {
  OVER_HEDGED: "SHORT is al groter dan de LONG · niets gedaan, graag controleren",
  SURVIVOR_IS_SHORT: "Alleen een SHORT over (LONG is gesloten) · geen LONG geopend",
  MANUAL_RELEASE_NOT_CONFIRMED: "Handmatige sluiting nog niet bevestigd",
  POSITION_CLOSED: "Positie is niet meer open",
  POSITION_UNREADABLE: "Positie niet betrouwbaar leesbaar",
  NOT_IN_RECOVERY_ANYMORE: "Staat al onder Auto Hedge",
};

export const OUTCOME_GROUPS = {
  ok: ["PROTECTED"],
  busy: ["PARTIAL", "PENDING", "QUEUED"],
  skipped: ["SKIPPED", "TOO_SMALL"],
  attention: ["NO_MARGIN", "FAILED", "UNKNOWN"],
};

export function outcomeLabel(item) {
  const outcome = String(item?.outcome || "").toUpperCase();
  if (outcome === "SKIPPED") return REASON_LABELS[item?.reason] || OUTCOME_LABELS.SKIPPED;
  return OUTCOME_LABELS[outcome] || outcome || "Onbekend";
}

function usd(value) {
  const n = Number(value);
  return Number.isFinite(n) ? `$${n.toFixed(2).replace(".", ",")}` : "—";
}

export function summarizeRehedgeAll(result) {
  const items = Array.isArray(result?.items) ? result.items : [];
  const count = (group) => items.filter((item) => OUTCOME_GROUPS[group].includes(String(item.outcome || "").toUpperCase())).length;
  return {
    found: Number(result?.found ?? items.length) || 0,
    protected: count("ok"),
    busy: count("busy"),
    skipped: count("skipped"),
    attention: count("attention"),
    ordersSent: Number(result?.ordersSent || 0),
    testMode: String(result?.mode || "").toUpperCase() === "SHADOW",
    rows: items.map((item) => ({
      symbol: String(item.symbol || "").replace(/USDT$/i, ""),
      outcome: String(item.outcome || "").toUpperCase(),
      label: outcomeLabel(item),
      longNotional: usd(item.longNotional),
      shortBefore: usd(item.shortNotionalBefore),
      shortAfter: usd(item.shortNotionalAfter),
      addedQty: Number(item.addedShortQty || 0),
      hedgePercent: item.hedgePercent == null ? "—" : `${Math.floor(Number(item.hedgePercent) * 10) / 10}%`,
    })),
  };
}
