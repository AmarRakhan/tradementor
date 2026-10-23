// Re-Hedge All 1.0 — pure presentation helpers (no trading logic; the server decides every size).

export const RECOVERY_STATUSES = ["RECOVERY", "REHEDGE_ARMED", "DISABLED", "MANUAL_RELEASE_PENDING", "MANUAL_RELEASE_UNCERTAIN"];

const ACTIVE_STATUSES = ["HEDGING", "HEDGED", "ADJUSTING", "BLOCKED", "ERROR", "PRECISION_BLOCKED"];

/** Build 623 (Amar 23-10): Re-Hedge All = everything back to 100%: Recovery pairs AND pairs halfway the afbouw
 *  (same rule as the server). Both sides: a remaining SHORT gets a LONG hedge. */
export function midLadder(pair) {
  const rec = pair && typeof pair.shortRecovery === "object" && pair.shortRecovery ? pair.shortRecovery : null;
  if (!rec || !rec.phase) return false;
  if (rec.phase === "REOPEN_CLOSE" || rec.phase === "REOPEN_OPEN" || Number(rec.stepsReached) > 0) return true;
  const target = Number(rec.lastTarget);
  const protectedQty = Number(pair.currentProtectedQty) || 0;
  return Number.isFinite(target) && target < protectedQty;
}

export function recoveryPairs(pairs) {
  return (Array.isArray(pairs) ? pairs : []).filter((pair) => {
    const status = String(pair?.status || "").toUpperCase();
    return RECOVERY_STATUSES.includes(status) || (ACTIVE_STATUSES.includes(status) && midLadder(pair));
  });
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
  OVER_HEDGED: "Hedge is al groter dan de positie · niets gedaan, graag controleren",
  ALREADY_FULLY_HEDGED: "Stond al 100% gehedged",
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
