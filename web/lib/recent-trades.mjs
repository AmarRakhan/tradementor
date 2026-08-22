export function activityTime(row = {}) {
  const direct = Number(row.timestampMs);
  if (Number.isFinite(direct) && direct > 0) return direct;
  const parsed = Date.parse(String(row.executedAt || ""));
  return Number.isFinite(parsed) ? parsed : 0;
}

export function stableActivityId(row = {}) {
  return String(row.id || row.exchangeTradeId || `${row.symbol || ""}:${row.side || ""}:${row.executedAt || ""}`);
}

export function newestActivityFirst(left, right) {
  const byTime = activityTime(right) - activityTime(left);
  return byTime || stableActivityId(right).localeCompare(stableActivityId(left), "en");
}

export function sortedActivity(rows) {
  return (Array.isArray(rows) ? rows : []).slice().sort(newestActivityFirst);
}

export function pageActivity(rows, loadedPages, pageSize = 100) {
  return sortedActivity(rows).slice(0, Math.max(1, loadedPages) * pageSize);
}

export function reliableReturnPct(row = {}) {
  for (const key of ["returnPct", "roePct", "roiPct"]) {
    if (row[key] === null || row[key] === undefined || row[key] === "") continue;
    const value = Number(row[key]);
    if (Number.isFinite(value)) return value;
  }
  const realized = Number(row.realizedPnlUsd);
  const closedValue = Number(row.closedValueUsd);
  if (Number.isFinite(realized) && Number.isFinite(closedValue) && closedValue > 0) {
    const basis = String(row.side || "").toUpperCase() === "SHORT" ? closedValue + realized : closedValue - realized;
    if (basis > 0) return realized / basis * 100;
  }
  const unrealized = Number(row.unrealizedPnlUsd);
  const executed = Number(row.executedNotionalUsd);
  if (Number.isFinite(unrealized) && Number.isFinite(executed) && executed > 0) return unrealized / executed * 100;
  return null;
}
