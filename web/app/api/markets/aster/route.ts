import { createHash } from "node:crypto";

const ASTER = "https://fapi.asterdex.com";
const CLOUD_API = "https://tradementor-api-604335232956.europe-west4.run.app";
const ALLOWED_INTERVALS = new Set(["1m", "5m", "15m", "1h", "4h", "1d"]);
const BOLLINGER_PERIOD = 20;
const BOLLINGER_DEVIATIONS = 2;
const CONCURRENCY = 10;
const MAX_ENRICH_SYMBOLS = 12;
const LEVERAGE_TTL_MS = 10 * 60_000;
const BB_TTL_MS = 45_000;
const FETCH_TIMEOUT_MS = 12_000;

type Timed<T> = { expiresAt: number; value: T };
type BbStatus = "above" | "between" | "below";
type BbResult = { status: BbStatus; upper: number; middle: number; lower: number };

const leverageCache = new Map<string, Timed<number>>();
const bbCache = new Map<string, Timed<BbResult>>();

function numberValue(value: unknown): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
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
      const detail = payload && typeof payload === "object" && "detail" in payload ? String((payload as { detail?: unknown }).detail) : body;
      throw new Error(detail || `HTTP ${response.status}`);
    }
    return payload;
  } finally {
    clearTimeout(timer);
  }
}

async function mapLimited<T, R>(values: T[], worker: (value: T) => Promise<R>): Promise<R[]> {
  const result = new Array<R>(values.length);
  let cursor = 0;
  const runners = Array.from({ length: Math.min(CONCURRENCY, values.length) }, async () => {
    while (true) {
      const index = cursor++;
      if (index >= values.length) return;
      result[index] = await worker(values[index]);
    }
  });
  await Promise.all(runners);
  return result;
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

async function bbFor(symbol: string, interval: string, livePrice: number): Promise<BbResult> {
  const key = `${interval}:${symbol}`;
  const cached = bbCache.get(key);
  if (cached && cached.expiresAt > Date.now()) {
    const { upper, middle, lower } = cached.value;
    return { status: livePrice > upper ? "above" : livePrice < lower ? "below" : "between", upper, middle, lower };
  }
  const url = new URL(`${ASTER}/fapi/v1/klines`);
  url.searchParams.set("symbol", symbol);
  url.searchParams.set("interval", interval);
  url.searchParams.set("limit", String(BOLLINGER_PERIOD));
  const payload = await jsonFetch(url.toString());
  if (!Array.isArray(payload)) throw new Error(`${symbol}: candles hebben een ongeldig formaat`);
  const closes = payload.map((row) => Array.isArray(row) ? numberValue(row[4]) : 0);
  const result = bollinger(closes, livePrice);
  bbCache.set(key, { expiresAt: Date.now() + BB_TTL_MS, value: result });
  return result;
}

function tickerMap(raw: unknown) {
  const tickers = Array.isArray(raw) ? raw : [];
  return new Map(tickers.filter((row): row is Record<string, unknown> => Boolean(row && typeof row === "object"))
    .map((row) => [String(row.symbol || "").toUpperCase(), row]));
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
      const tickers = tickerMap(await jsonFetch(`${ASTER}/fapi/v1/ticker/24hr`));
      const accountKey = createHash("sha256").update(authorization).digest("hex").slice(0, 20);
      const rows = await mapLimited(symbols, async (symbol) => {
        try {
          const ticker = tickers.get(symbol) || {};
          const lastPrice = numberValue(ticker.lastPrice);
          if (lastPrice <= 0) throw new Error(`${symbol}: actuele lastPrice ontbreekt`);
          const [maxLeverage, bb] = await Promise.all([
            maximumLeverage(symbol, authorization, accountKey),
            bbFor(symbol, interval, lastPrice),
          ]);
          return {
            ok: true as const,
            symbol,
            maxLeverage,
            bbStatus: bb.status,
            bbUpper: bb.upper,
            bbMiddle: bb.middle,
            bbLower: bb.lower,
          };
        } catch (reason) {
          return { ok: false as const, symbol, detail: reason instanceof Error ? reason.message : `${symbol}: enrichment mislukt` };
        }
      });
      const markets = rows.filter((row) => row.ok);
      const errors = rows.filter((row) => !row.ok);
      return Response.json({ interval, markets, errors, updatedAt: Date.now() }, { headers: { "Cache-Control": "private, no-store" } });
    }

    if (mode !== "base") {
      return Response.json({ detail: "Ongeldige Markets-modus" }, { status: 422 });
    }

    const [exchangeInfoRaw, tickersRaw] = await Promise.all([
      jsonFetch(`${ASTER}/fapi/v1/exchangeInfo`),
      jsonFetch(`${ASTER}/fapi/v1/ticker/24hr`),
    ]);
    const exchangeInfo = exchangeInfoRaw && typeof exchangeInfoRaw === "object" ? exchangeInfoRaw as Record<string, unknown> : {};
    const symbols = Array.isArray(exchangeInfo.symbols) ? exchangeInfo.symbols : [];
    const tickers = tickerMap(tickersRaw);
    const activeSymbols = symbols.filter((row): row is Record<string, unknown> => Boolean(row && typeof row === "object"))
      .filter((row) => String(row.quoteAsset || "").toUpperCase() === "USDT")
      .filter((row) => String(row.contractType || "").toUpperCase() === "PERPETUAL")
      .filter((row) => String(row.status || "").toUpperCase() === "TRADING")
      .map((row) => String(row.symbol || "").toUpperCase())
      .filter(Boolean);

    const markets = activeSymbols.map((symbol) => {
      const ticker = tickers.get(symbol) || {};
      const lastPrice = numberValue(ticker.lastPrice);
      if (lastPrice <= 0) return null;
      return {
        symbol,
        baseAsset: symbol.endsWith("USDT") ? symbol.slice(0, -4) : symbol,
        quoteAsset: "USDT",
        lastPrice,
        change24hPct: numberValue(ticker.priceChangePercent),
        quoteVolume24h: Math.max(0, numberValue(ticker.quoteVolume)),
        maxLeverage: null,
        bbStatus: null,
        bbUpper: null,
        bbMiddle: null,
        bbLower: null,
      };
    }).filter((row): row is NonNullable<typeof row> => Boolean(row));

    markets.sort((a, b) => b.quoteVolume24h - a.quoteVolume24h || a.symbol.localeCompare(b.symbol));
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
