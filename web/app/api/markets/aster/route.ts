import { createHash } from "node:crypto";

const ASTER = "https://fapi.asterdex.com";
const CLOUD_API = "https://tradementor-api-604335232956.europe-west4.run.app";
const ALLOWED_INTERVALS = new Set(["1m", "5m", "15m", "1h", "4h", "1d"]);
const BOLLINGER_PERIOD = 20;
const BOLLINGER_DEVIATIONS = 2;
const MAX_ENRICH_SYMBOLS = 8;
const LEVERAGE_TTL_MS = 6 * 60 * 60_000;
const FETCH_TIMEOUT_MS = 12_000;
const ASTER_MIN_REQUEST_SPACING_MS = 450;

type Timed<T> = { expiresAt: number; value: T };
type BbStatus = "above" | "between" | "below";
type BbResult = { status: BbStatus; upper: number; middle: number; lower: number };

const leverageCache = new Map<string, Timed<number>>();
const bbCache = new Map<string, Timed<BbResult>>();
let asterQueue: Promise<void> = Promise.resolve();
let lastAsterRequestAt = 0;

function numberValue(value: unknown): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function sleep(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}

function bbTtlMs(interval: string) {
  if (interval === "1m") return 45_000;
  if (interval === "5m") return 2 * 60_000;
  if (interval === "15m") return 5 * 60_000;
  if (interval === "1h") return 10 * 60_000;
  if (interval === "4h") return 30 * 60_000;
  return 60 * 60_000;
}

function bollinger(closes: number[], livePrice: number): BbResult {
  const sample = closes.slice(-BOLLINGER_PERIOD);
  if (sample.length < BOLLINGER_PERIOD || sample.some((value) => !Number.isFinite(value) || value <= 0)) {
    throw new Error("Onvoldoende geldige candles voor Bollinger Bands");
  }
  const middle = sample.reduce((sum, value) => sum + value, 0) / sample.length;
  const variance = sample.reduce((sum, value) => sum + ((value - middle) ** 2), 0) / sample.length;
  const deviation = Math.sqrt(variance);
  const upper = middle + BOLLINGER_DEVIATIONS * deviation;
  const lower = middle - BOLLINGER_DEVIATIONS * deviation;
  const status: BbStatus = livePrice > upper ? "above" : livePrice < lower ? "below" : "between";
  return { status, upper, middle, lower };
}

async function jsonFetch(url: string, init?: RequestInit) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(url, { ...init, cache: "no-store", signal: controller.signal });
    const body = await response.text();
    let payload: unknown;
    try { payload = JSON.parse(body); } catch { payload = null; }
    if (!response.ok) {
      const detail = payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail?: unknown }).detail)
        : body;
      throw new Error(detail || `HTTP ${response.status}`);
    }
    if (payload && typeof payload === "object" && "code" in payload && numberValue((payload as Record<string, unknown>).code) < 0) {
      throw new Error(JSON.stringify(payload));
    }
    return payload;
  } finally {
    clearTimeout(timer);
  }
}

async function queuedAsterJson(url: string) {
  let release!: () => void;
  const previous = asterQueue;
  asterQueue = new Promise<void>((resolve) => { release = resolve; });
  await previous;
  try {
    const waitMs = Math.max(0, lastAsterRequestAt + ASTER_MIN_REQUEST_SPACING_MS - Date.now());
    if (waitMs) await sleep(waitMs);
    lastAsterRequestAt = Date.now();
    return await jsonFetch(url);
  } finally {
    release();
  }
}

async function maximumLeverage(symbol: string, authorization: string, accountKey: string): Promise<number> {
  const key = `${accountKey}:${symbol}`;
  const cached = leverageCache.get(key);
  if (cached && cached.expiresAt > Date.now()) return cached.value;
  const url = new URL(`${CLOUD_API}/v1/me/aster/strategy2/leverage-tiers`);
  url.searchParams.set("symbol", symbol);
  const payload = await jsonFetch(url.toString(), { headers: { Authorization: authorization } }) as Record<string, unknown>;
  const tiers = Array.isArray(payload?.tiers) ? payload.tiers : [];
  const maximum = tiers.reduce((best, row) => {
    if (!row || typeof row !== "object") return best;
    return Math.max(best, numberValue((row as Record<string, unknown>).maxLeverage));
  }, 0);
  if (maximum < 1) throw new Error(`${symbol}: maximale leverage ontbreekt in Aster leverageBracket`);
  leverageCache.set(key, { expiresAt: Date.now() + LEVERAGE_TTL_MS, value: maximum });
  return maximum;
}

async function bbFor(symbol: string, interval: string): Promise<BbResult> {
  const key = `${interval}:${symbol}`;
  const cached = bbCache.get(key);
  if (cached && cached.expiresAt > Date.now()) return cached.value;

  const url = new URL(`${ASTER}/fapi/v1/klines`);
  url.searchParams.set("symbol", symbol);
  url.searchParams.set("interval", interval);
  url.searchParams.set("limit", String(BOLLINGER_PERIOD));
  const payload = await queuedAsterJson(url.toString());
  if (!Array.isArray(payload)) throw new Error(`${symbol}: candles hebben een ongeldig formaat`);
  const closes = payload.map((row) => Array.isArray(row) ? numberValue(row[4]) : 0);
  const livePrice = closes.at(-1) || 0;
  if (livePrice <= 0) throw new Error(`${symbol}: actuele candle-close ontbreekt`);
  const result = bollinger(closes, livePrice);
  bbCache.set(key, { expiresAt: Date.now() + bbTtlMs(interval), value: result });
  return result;
}

function parseEnrichSymbols(url: URL) {
  const requested = (url.searchParams.get("symbols") || "").split(",")
    .map((value) => value.trim().toUpperCase())
    .filter(Boolean);
  const symbols = Array.from(new Set(requested));
  if (!symbols.length || symbols.length > MAX_ENRICH_SYMBOLS || symbols.some((symbol) => !/^[A-Z0-9]+USDT$/.test(symbol))) {
    throw new Error(`Enrichment ondersteunt 1-${MAX_ENRICH_SYMBOLS} geldige USDT-symbolen per batch`);
  }
  return symbols;
}

function marketObjects(payload: unknown, depth = 0): Record<string, unknown>[] {
  if (depth > 6 || payload == null) return [];
  if (Array.isArray(payload)) return payload.flatMap((value) => marketObjects(value, depth + 1));
  if (typeof payload !== "object") return [];
  const row = payload as Record<string, unknown>;
  const symbol = String(row.symbol ?? row.market ?? row.pair ?? row.ticker ?? "").toUpperCase();
  const price = numberValue(row.lastPrice ?? row.last_price ?? row.price ?? row.markPrice ?? row.mark_price ?? row.currentPrice ?? row.current_price);
  const own = symbol.endsWith("USDT") && price > 0 ? [row] : [];
  const nested = Object.values(row).flatMap((value) => marketObjects(value, depth + 1));
  return [...own, ...nested];
}

function rowsFromFocusMarkets(payload: unknown) {
  const unique = new Map<string, ReturnType<typeof toMarketRow>>();
  for (const row of marketObjects(payload)) {
    const parsed = toMarketRow(row);
    if (parsed && !unique.has(parsed.symbol)) unique.set(parsed.symbol, parsed);
  }
  const rows = Array.from(unique.values()).filter((row): row is NonNullable<typeof row> => Boolean(row));
  rows.sort((a, b) => b.quoteVolume24h - a.quoteVolume24h || a.symbol.localeCompare(b.symbol));
  return rows;
}

function toMarketRow(row: Record<string, unknown>) {
  const symbol = String(row.symbol ?? row.market ?? row.pair ?? row.ticker ?? "").toUpperCase();
  if (!symbol.endsWith("USDT")) return null;
  const lastPrice = numberValue(row.lastPrice ?? row.last_price ?? row.price ?? row.markPrice ?? row.mark_price ?? row.currentPrice ?? row.current_price);
  if (lastPrice <= 0) return null;

  let change24hPct = numberValue(
    row.change24hPct ?? row.change_24h_pct ?? row.priceChangePercent ?? row.price_change_percent ?? row.change24h ?? row.change_pct ?? row.changePct,
  );
  if (row.change !== undefined && row.change24hPct === undefined && row.priceChangePercent === undefined) {
    const fractional = numberValue(row.change);
    change24hPct = Math.abs(fractional) <= 2 ? fractional * 100 : fractional;
  }

  return {
    symbol,
    baseAsset: String(row.baseAsset ?? row.base_asset ?? symbol.slice(0, -4)),
    quoteAsset: "USDT",
    lastPrice,
    change24hPct,
    quoteVolume24h: Math.max(0, numberValue(
      row.quoteVolume24h ?? row.quote_volume_24h ?? row.quoteVolume ?? row.quote_volume ?? row.volume24h ?? row.volume_24h ?? row.volume,
    )),
    maxLeverage: null as number | null,
    bbStatus: null as BbStatus | null,
    bbUpper: null as number | null,
    bbMiddle: null as number | null,
    bbLower: null as number | null,
  };
}

export async function GET(request: Request) {
  const authorization = request.headers.get("authorization") || "";
  if (!authorization.startsWith("Bearer ")) {
    return Response.json({ detail: "Firebase ID-token ontbreekt" }, { status: 401 });
  }
  const url = new URL(request.url);
  const interval = url.searchParams.get("interval") || "15m";
  if (!ALLOWED_INTERVALS.has(interval)) {
    return Response.json({ detail: "Ongeldig Markets-timeframe" }, { status: 422 });
  }
  const mode = url.searchParams.get("mode") || "base";

  try {
    if (mode === "enrich") {
      const symbols = parseEnrichSymbols(url);
      const accountKey = createHash("sha256").update(authorization).digest("hex").slice(0, 20);
      const rows = [] as Array<Record<string, unknown>>;
      const errors = [] as Array<{ symbol: string; detail: string }>;

      for (const symbol of symbols) {
        try {
          const [maxLeverage, bb] = await Promise.all([
            maximumLeverage(symbol, authorization, accountKey),
            bbFor(symbol, interval),
          ]);
          rows.push({
            symbol,
            maxLeverage,
            bbStatus: bb.status,
            bbUpper: bb.upper,
            bbMiddle: bb.middle,
            bbLower: bb.lower,
          });
        } catch (reason) {
          errors.push({ symbol, detail: reason instanceof Error ? reason.message : `${symbol}: enrichment mislukt` });
        }
      }

      return Response.json({ interval, markets: rows, errors, updatedAt: Date.now() }, {
        headers: { "Cache-Control": "private, no-store" },
      });
    }

    if (mode !== "base") {
      return Response.json({ detail: "Ongeldige Markets-modus" }, { status: 422 });
    }

    const focusUrl = `${CLOUD_API}/v1/me/aster/strategy2/focus/markets`;
    const focusPayload = await jsonFetch(focusUrl, { headers: { Authorization: authorization } });
    const markets = rowsFromFocusMarkets(focusPayload);
    if (!markets.length) throw new Error("Aster market-universe bevat momenteel geen geldige USDT perpetuals");

    return Response.json({
      exchange: "aster",
      contractType: "PERPETUAL",
      quoteAsset: "USDT",
      interval,
      bollinger: { period: BOLLINGER_PERIOD, deviations: BOLLINGER_DEVIATIONS },
      marketCount: markets.length,
      updatedAt: Date.now(),
      markets,
    }, { headers: { "Cache-Control": "private, no-store" } });
  } catch (reason) {
    const detail = reason instanceof Error ? reason.message : "Aster Markets kon niet betrouwbaar worden geladen";
    return Response.json({ detail }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
