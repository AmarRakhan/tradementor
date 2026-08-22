export const ASTER_SNAPSHOT_SCHEMA = 1;
const KEY_PREFIX = "tradementor.asterSnapshot.v1";

const isRecord = (value) => Boolean(value) && typeof value === "object" && !Array.isArray(value);

export function asterSnapshotCacheKey(uid) {
  return `${KEY_PREFIX}:${encodeURIComponent(String(uid || ""))}:aster`;
}

export function isValidAsterSnapshotData(value) {
  if (!isRecord(value)) return false;
  return typeof value.configured === "boolean"
    && Array.isArray(value.positions)
    && isRecord(value.strategy2)
    && typeof value.historyAvailable === "boolean"
    && Array.isArray(value.closedTrades)
    && Array.isArray(value.realizedEvents);
}


const PRESERVED_ACCOUNT_FIELDS = [
  "equity", "walletBalance", "availableBalance", "activeTradeCapital",
  "activePositions", "maintenanceMargin", "marginRatio", "unrealizedPnl",
];

export function preserveConfirmedAsterValues(previous, incoming) {
  if (!isRecord(incoming)) throw new Error("Onvolledige Aster-snapshot ontvangen.");
  if (!isRecord(previous)) return incoming;
  const merged = { ...previous, ...incoming };
  for (const key of PRESERVED_ACCOUNT_FIELDS) {
    if (!(key in incoming) || incoming[key] === null || incoming[key] === undefined) {
      if (key in previous) merged[key] = previous[key];
    }
  }
  if (!isRecord(incoming.strategy2) && isRecord(previous.strategy2)) merged.strategy2 = previous.strategy2;
  return merged;
}

export function mergeCompleteAsterSnapshot(account, history) {
  if (!isRecord(account) || !isRecord(history)) throw new Error("Onvolledige Aster-snapshot ontvangen.");
  const merged = { ...account, ...history };
  if (!isValidAsterSnapshotData(merged)) throw new Error("De nieuwe Aster-snapshot is niet volledig bevestigd.");
  return merged;
}

export function loadAsterSnapshot(storage, uid) {
  if (!storage || !uid) return null;
  try {
    const raw = storage.getItem(asterSnapshotCacheKey(uid));
    if (!raw) return null;
    const saved = JSON.parse(raw);
    if (saved?.schema !== ASTER_SNAPSHOT_SCHEMA
      || saved?.uid !== uid
      || saved?.exchange !== "aster"
      || !Number.isFinite(saved?.updatedAt)
      || !isValidAsterSnapshotData(saved?.data)) return null;
    return { data: saved.data, updatedAt: saved.updatedAt };
  } catch {
    return null;
  }
}

export function saveAsterSnapshot(storage, uid, data, updatedAt) {
  if (!storage || !uid || !isValidAsterSnapshotData(data) || !Number.isFinite(updatedAt)) return false;
  try {
    storage.setItem(asterSnapshotCacheKey(uid), JSON.stringify({
      schema: ASTER_SNAPSHOT_SCHEMA,
      uid,
      exchange: "aster",
      updatedAt,
      data,
    }));
    return true;
  } catch {
    return false;
  }
}

export function clearAsterSnapshot(storage, uid) {
  if (!storage || !uid) return;
  try { storage.removeItem(asterSnapshotCacheKey(uid)); } catch { /* storage may be unavailable */ }
}

export async function withBoundedRetry(operation, options = {}) {
  const attempts = Math.max(1, Number(options.attempts || 2));
  const delays = Array.isArray(options.delays) ? options.delays : [300];
  let lastError;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try { return await operation(attempt); }
    catch (error) {
      lastError = error;
      if (attempt + 1 >= attempts) break;
      const delay = Math.max(0, Number(delays[Math.min(attempt, delays.length - 1)] || 0));
      if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }
  throw lastError;
}
