function finite(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function applyAsterRealtimeMark(snapshot, event) {
  if (!snapshot || typeof snapshot !== "object" || !event || typeof event !== "object") return snapshot;
  const symbol = String(event.symbol ?? "").toUpperCase().trim();
  const mark = finite(event.markPrice);
  if (!symbol || mark === null || mark <= 0) return snapshot;
  const positions = Array.isArray(snapshot.positions) ? snapshot.positions : [];
  let changed = false;
  const realtimeAt = finite(event.receivedAtMs) ?? Date.now();
  const nextPositions = positions.map((raw) => {
    if (!raw || typeof raw !== "object" || String(raw.symbol ?? "").toUpperCase() !== symbol) return raw;
    changed = true;
    return {
      ...raw,
      // Market decoration only. Never recompute notional, PnL or equity in the browser.
      markPrice: mark,
      realtimeMarketAt: realtimeAt,
    };
  });
  if (!changed) return snapshot;
  return {
    ...snapshot,
    positions: nextPositions,
    realtimeMarketAt: realtimeAt,
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
