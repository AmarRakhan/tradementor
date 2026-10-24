// Build 652: gem. max drawdown vanaf instap (LONG links, SHORT rechts). Alleen weergave; de server rekent.

/** "−4,8%" (één decimaal, echte minteken); onbekend = "—". */
export function formatDrawdown(pct) {
  if (typeof pct !== "number" || !Number.isFinite(pct)) return "—";
  const value = Math.abs(pct).toLocaleString("nl-NL", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return pct === 0 ? "0,0%" : `−${value}%`;
}

/** Ondertekst op de tegel: wat het getal is, of dat het nog berekend wordt. */
export function drawdownCaption(side, refreshing) {
  if (!side || typeof side.avgMaxDrawdownPct !== "number") return refreshing ? "Wordt berekend…" : "Nog geen posities";
  return "Gemiddeld vanaf instap";
}

/** Leest het serverantwoord veilig in. */
export function normalizeDrawdown(payload) {
  const side = (raw) => {
    const value = raw && typeof raw.avgMaxDrawdownPct === "number" && Number.isFinite(raw.avgMaxDrawdownPct) ? raw.avgMaxDrawdownPct : null;
    const count = raw && Number.isFinite(Number(raw.count)) ? Number(raw.count) : 0;
    return { avgMaxDrawdownPct: value, count };
  };
  const p = payload && typeof payload === "object" ? payload : {};
  return { long: side(p.long), short: side(p.short), refreshing: p.refreshing === true, complete: p.complete === true };
}
