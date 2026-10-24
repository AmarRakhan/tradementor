// Build 648: Trade Historie — remembered list per account and the export file. Pure helpers (no React, no network).

export const TRADE_HISTORY_CACHE_PREFIX = "tradementor.tradeHistory.v1.";
export const TRADE_HISTORY_CACHE_MAX_ROWS = 300;
export const SYNC_STEP_PAUSE_MS = 4000;
export const SYNC_RETRY_PAUSE_MS = 6000;
export const SYNC_MAX_STEPS = 120;
export const BACKGROUND_SYNC_INTERVAL_MS = 10 * 60 * 1000;

export function tradeHistoryCacheKey(uid) {
  return `${TRADE_HISTORY_CACHE_PREFIX}${String(uid || "").trim()}`;
}

/** The remembered list for this account, or null. Never throws (private mode, blocked storage, bad JSON). */
export function readTradeHistoryCache(storage, uid) {
  if (!uid || !storage) return null;
  try {
    const raw = storage.getItem(tradeHistoryCacheKey(uid));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || !Array.isArray(parsed.rows)) return null;
    return {
      rows: parsed.rows.filter((row) => row && typeof row === "object"),
      savedAt: typeof parsed.savedAt === "number" ? parsed.savedAt : 0,
      source: parsed.source === "journal" ? "journal" : "legacy",
    };
  } catch {
    return null;
  }
}

export function writeTradeHistoryCache(storage, uid, rows, source, now = Date.now()) {
  if (!uid || !storage || !Array.isArray(rows)) return false;
  try {
    storage.setItem(tradeHistoryCacheKey(uid), JSON.stringify({
      rows: rows.slice(0, TRADE_HISTORY_CACHE_MAX_ROWS), savedAt: now, source: source === "journal" ? "journal" : "legacy",
    }));
    return true;
  } catch {
    return false;
  }
}

function pad(n) {
  return String(n).padStart(2, "0");
}

/** tradementor-trade-historie-2026-10-24-0915.json (local time of the phone). */
export function tradeHistoryFileName(date = new Date()) {
  return `tradementor-trade-historie-${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}.json`;
}

/** The file content: the server export plus which app build made it. */
export function tradeHistoryFileContent(exportPayload, webappBuild) {
  const body = exportPayload && typeof exportPayload === "object" ? exportPayload : {};
  return JSON.stringify({ ...body, app: { ...(body.app || {}), webappBuild: String(webappBuild || "") } }, null, 2);
}

/** Progress text for the download button while the full history is being built. */
export function syncProgressLabel(result) {
  const percent = Number(result?.progress?.percent);
  if (!Number.isFinite(percent)) return "Historie ophalen…";
  return `Historie ophalen… ${Math.max(0, Math.min(100, Math.round(percent)))}%`;
}

/** Same trade, two sources: journal rows have `id`, legacy rows `exchangeTradeId`. */
export function tradeRowKey(row, index = 0) {
  if (!row || typeof row !== "object") return `row-${index}`;
  return String(row.id || row.exchangeTradeId || [row.symbol, row.side, row.closedAt, row.realizedPnlUsd].join("|"));
}
