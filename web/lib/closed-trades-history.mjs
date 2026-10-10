/** Shared read-only presentation contract for persisted Aster closes.
 * Never infer margin from notional/leverage: partial closes and DCA make that unsafe.
 */
export function closedTradeTime(row = {}) {
  const value = row.closedAt ?? row.timestampMs;
  const n = typeof value === "number" ? value : Date.parse(String(value || ""));
  return Number.isFinite(n) && n > 0 ? (n < 1e10 ? n * 1000 : n) : null;
}
export function verifiedClosedTradeMargin(row = {}) {
  for (const key of ["executedMarginUsd", "marginUsd", "initialMarginUsd"]) {
    const raw = row[key];
    if (raw === "" || raw == null) continue;
    const value = Number(raw);
    if (Number.isFinite(value) && value >= 0) return value;
  }
  return null;
}
export function closedTradeDurationMs(row = {}) {
  const close = closedTradeTime(row);
  const open = row.openedAt == null ? NaN : Date.parse(String(row.openedAt));
  return close !== null && Number.isFinite(open) && open > 0 && close >= open ? close - open : null;
}
export function closedTradeStableKey(row = {}) {
  return String(row.recordId || row.id || row.exchangeTradeId || [row.symbol,row.side,row.closedAt,row.realizedPnlUsd].join("|"));
}
export function uniqueClosedTrades(rows = []) {
  const seen = new Set();
  return rows.filter(row => {
    const key = closedTradeStableKey(row);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).sort((a,b) => (closedTradeTime(b) ?? 0)-(closedTradeTime(a) ?? 0) || closedTradeStableKey(b).localeCompare(closedTradeStableKey(a)));
}
