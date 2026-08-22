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

  const pnl = finite(row.unrealizedPnl ?? row.unRealizedProfit);
  const notional = finite(row.notionalUsd ?? row.positionNotional ?? row.size);
  return pnl !== null && notional !== null && notional > 0 ? pnl / notional * 100 : null;
}

export function topProfitPositions(rows, limit = 5) {
  return (Array.isArray(rows) ? rows : [])
    .filter((row) => finite(row?.quantity ?? row?.positionAmt) !== null && Math.abs(Number(row.quantity ?? row.positionAmt)) > 0)
    .filter((row) => finite(row?.unrealizedPnl ?? row?.unRealizedProfit) !== null)
    .slice()
    .sort((a, b) => Number(b.unrealizedPnl ?? b.unRealizedProfit) - Number(a.unrealizedPnl ?? a.unRealizedProfit) || positionId(a).localeCompare(positionId(b)))
    .slice(0, limit);
}
