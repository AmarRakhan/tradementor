// Build 652/655: gem. max drawdown vanaf instap (LONG links, SHORT rechts), alleen afgeronde trades.
// Groot getal = laatste 90 dagen; kleine regel = laatste 7 dagen (zie je of een nieuwe strategie minder diep gaat).
// Alleen weergave; de server rekent en geeft alleen een volledig doorgerekend getal.

/** "−4,8%" (één decimaal, echte minteken); onbekend = "—". */
export function formatDrawdown(pct) {
  if (typeof pct !== "number" || !Number.isFinite(pct)) return "—";
  const value = Math.abs(pct).toLocaleString("nl-NL", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return pct === 0 ? "0,0%" : `−${value}%`;
}

/** Ondertekst op de tegel: de 7-dagenregel, of dat het nog berekend wordt. */
export function drawdownCaption(side, refreshing, recentDays = 7) {
  if (!side || typeof side.avgMaxDrawdownPct !== "number") return refreshing ? "Wordt berekend…" : "Nog geen gesloten trades";
  if (typeof side.recentAvgMaxDrawdownPct !== "number") return `${recentDays} dagen: geen trades`;
  return `${recentDays} dagen: ${formatDrawdown(side.recentAvgMaxDrawdownPct)}`;
}

/** Leest het serverantwoord veilig in. */
export function normalizeDrawdown(payload) {
  const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const int = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);
  const side = (raw) => ({
    avgMaxDrawdownPct: num(raw?.avgMaxDrawdownPct), count: int(raw?.count),
    recentAvgMaxDrawdownPct: num(raw?.recentAvgMaxDrawdownPct), recentCount: int(raw?.recentCount),
  });
  const p = payload && typeof payload === "object" ? payload : {};
  return {
    long: side(p.long), short: side(p.short), refreshing: p.refreshing === true, complete: p.complete === true,
    windowDays: int(p.windowDays) || 90, recentDays: int(p.recentDays) || 7,
  };
}
