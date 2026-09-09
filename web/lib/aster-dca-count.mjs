function record(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function finite(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function asterDcaPositionKey(position) {
  const row = record(position);
  const symbol = String(row.symbol ?? "").toUpperCase().replace(/[\/_-]/g, "");
  const side = String(row.side ?? row.positionSide ?? "").toUpperCase();
  return `${symbol}|${side}`;
}

export function effectiveAsterDcaCount(position, strategy2) {
  const row = record(position);
  const state = record(strategy2);
  const managed = record(state.multiBbPositions);
  const runtime = record(managed[asterDcaPositionKey(row)]);
  const runtimeDca = finite(runtime.dcaCount);
  if (runtimeDca !== null && runtimeDca >= 0) return Math.max(0, Math.round(runtimeDca));
  const directDca = finite(row.dcaCount);
  return directDca === null ? 0 : Math.max(0, Math.round(directDca));
}

export function totalAsterDca(positions, strategy2) {
  return (Array.isArray(positions) ? positions : []).reduce((total, position) => {
    const row = record(position);
    const quantity = finite(row.quantity ?? row.positionAmt ?? row.size);
    if (quantity !== null && quantity === 0) return total;
    return total + effectiveAsterDcaCount(row, strategy2);
  }, 0);
}
