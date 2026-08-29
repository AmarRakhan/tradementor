function finite(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function positionQuantity(row) {
  return Math.abs(finite(row?.quantity ?? row?.positionAmt ?? row?.signedQuantity) ?? 0);
}

export function applyAsterRealtimeMark(snapshot, event) {
  if (!snapshot || typeof snapshot !== "object" || !event || typeof event !== "object") return snapshot;
  const symbol = String(event.symbol ?? "").toUpperCase().trim();
  const mark = finite(event.markPrice);
  if (!symbol || mark === null || mark <= 0) return snapshot;
  const positions = Array.isArray(snapshot.positions) ? snapshot.positions : [];
  let changed = false;
  const nextPositions = positions.map((raw) => {
    if (!raw || typeof raw !== "object" || String(raw.symbol ?? "").toUpperCase() !== symbol) return raw;
    const entry = finite(raw.entryPrice) ?? 0;
    const quantity = positionQuantity(raw);
    const side = String(raw.side ?? "").toUpperCase();
    const unrealized = quantity > 0 && entry > 0
      ? (side === "SHORT" ? (entry - mark) : (mark - entry)) * quantity
      : finite(raw.unrealizedPnl);
    changed = true;
    return {
      ...raw,
      markPrice: mark,
      ...(quantity > 0 ? { notionalUsd: quantity * mark } : {}),
      ...(unrealized !== null ? { unrealizedPnl: unrealized } : {}),
      realtimeMarketAt: finite(event.receivedAtMs) ?? Date.now(),
    };
  });
  if (!changed) return snapshot;
  const totalPnl = nextPositions.reduce((sum, row) => sum + (finite(row?.unrealizedPnl) ?? 0), 0);
  return {
    ...snapshot,
    positions: nextPositions,
    unrealizedPnl: totalPnl,
    realtimeMarketAt: finite(event.receivedAtMs) ?? Date.now(),
    realtimeTransportLatencyMs: finite(event.transportLatencyMs),
  };
}

export function parseSseChunk(buffer, chunk) {
  const text = `${buffer}${chunk}`.replace(/\r\n/g, "\n");
  const blocks = text.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events = [];
  for (const block of blocks) {
    const data = block.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
    if (!data) continue;
    try { events.push(JSON.parse(data)); } catch { /* malformed frame is ignored */ }
  }
  return { rest, events };
}
