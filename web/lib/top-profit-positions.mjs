function finite(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function positionId(row) {
  return String(row.positionId ?? row.id ?? `${String(row.symbol ?? "").toUpperCase()}|${String(row.side ?? row.positionSide ?? "").toUpperCase()}`);
}

export function authoritativePositionReturnPct(row) {
  for (const key of ["returnPct", "roePct", "roiPct"]) {
    const value = finite(row[key]);
    if (value !== null) return value;
  }

  const pnl = finite(row.unrealizedPnl);
  let notional = finite(row.notionalUsd);
  if (notional === null) {
    const quantity = finite(row.quantity ?? row.positionAmt);
    const markPrice = finite(row.markPrice);
    if (quantity !== null && markPrice !== null) notional = Math.abs(quantity * markPrice);
  }
  return pnl !== null && notional !== null && notional > 0 ? pnl / notional * 100 : null;
}

export function topProfitPositions(rows, limit = 5) {
  return (Array.isArray(rows) ? rows : [])
    .filter((row) => finite(row?.quantity ?? row?.positionAmt) !== null && Math.abs(Number(row.quantity ?? row.positionAmt)) > 0)
    .filter((row) => finite(row?.unrealizedPnl) !== null)
    .slice()
    .sort((a, b) => Number(b.unrealizedPnl) - Number(a.unrealizedPnl) || positionId(a).localeCompare(positionId(b)))
    .slice(0, limit);
}
