import { dominancePresentation } from "@/lib/portfolio-impact-battle.mjs";

const ASTER = "https://fapi.asterdex.com";
const MAX_SYMBOLS = 16;
const FETCH_TIMEOUT_MS = 8_000;
const DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT"];

type Timeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "24h";
type FrameConfig = { interval: string; windowMs: number; limit: number; scalePct: number; ttlMs: number };
type Candle = { openTime: number; closeTime: number; open: number; high: number; low: number; close: number };
type SymbolPressure = { symbol: string; score: number; returnPct: number; price: number; candles: number; momentum: number; trend: number };
type CacheEntry = { expiresAt: number; value: Record<string, unknown> };

const FRAMES: Record<Timeframe, FrameConfig> = {
  "1m": { interval: "1m", windowMs: 60_000, limit: 4, scalePct: 0.16, ttlMs: 12_000 },
  "5m": { interval: "1m", windowMs: 5 * 60_000, limit: 7, scalePct: 0.34, ttlMs: 20_000 },
  "15m": { interval: "1m", windowMs: 15 * 60_000, limit: 17, scalePct: 0.65, ttlMs: 35_000 },
  "1h": { interval: "5m", windowMs: 60 * 60_000, limit: 14, scalePct: 1.15, ttlMs: 60_000 },
  "4h": { interval: "15m", windowMs: 4 * 60 * 60_000, limit: 18, scalePct: 2.10, ttlMs: 120_000 },
  "24h": { interval: "1h", windowMs: 24 * 60 * 60_000, limit: 26, scalePct: 4.25, ttlMs: 300_000 },
};
const cache = new Map<string, CacheEntry>();

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}
function finite(value: unknown) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}
function parseSymbols(raw: string) {
  const requested = raw.split(",").map((value) => value.trim().toUpperCase().replace(/[\/_-]/g, "")).filter(Boolean);
  if (requested.some((symbol) => !/^[A-Z0-9]+USDT$/.test(symbol))) throw new Error("Ongeldig Aster-symbool in marktdruk-aanvraag");
  const unique = Array.from(new Set(requested));
  for (const symbol of DEFAULT_SYMBOLS) {
    if (unique.length >= 8) break;
    if (!unique.includes(symbol)) unique.push(symbol);
  }
  return unique.slice(0, MAX_SYMBOLS);
}

async function jsonFetch(url: string) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(url, { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error(`Aster candles HTTP ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

function parseCandles(payload: unknown): Candle[] {
  if (!Array.isArray(payload)) return [];
  return payload.map((row) => {
    if (!Array.isArray(row)) return null;
    const candle = {
      openTime: finite(row[0]),
      open: finite(row[1]),
      high: finite(row[2]),
      low: finite(row[3]),
      close: finite(row[4]),
      closeTime: finite(row[6]) || finite(row[0]),
    };
    return candle.open > 0 && candle.high > 0 && candle.low > 0 && candle.close > 0 ? candle : null;
  }).filter((row): row is Candle => Boolean(row));
}

function regressionTrendPct(candles: Candle[]) {
  if (candles.length < 2) return 0;
  const n = candles.length;
  const meanX = (n - 1) / 2;
  const meanY = candles.reduce((sum, candle) => sum + candle.close, 0) / n;
  let numerator = 0;
  let denominator = 0;
  for (let i = 0; i < n; i += 1) {
    numerator += (i - meanX) * (candles[i].close - meanY);
    denominator += (i - meanX) ** 2;
  }
  if (denominator <= 0 || meanY <= 0) return 0;
  const slope = numerator / denominator;
  return slope * (n - 1) / meanY * 100;
}

function analyze(symbol: string, candles: Candle[], config: FrameConfig): SymbolPressure | null {
  if (candles.length < 2) return null;
  const last = candles.at(-1)!;
  const targetTime = last.closeTime - config.windowMs;
  let anchor = candles[0];
  for (const candle of candles) {
    if (candle.openTime <= targetTime) anchor = candle;
    else break;
  }
  const windowCandles = candles.filter((candle) => candle.closeTime > targetTime);
  if (!windowCandles.length || anchor.open <= 0) return null;
  const returnPct = (last.close - anchor.open) / anchor.open * 100;
  const price = Math.tanh(returnPct / config.scalePct) * 100;
  const body = windowCandles.reduce((sum, candle) => {
    const range = Math.max(candle.high - candle.low, candle.open * 0.000001);
    return sum + clamp((candle.close - candle.open) / range, -1, 1);
  }, 0) / windowCandles.length * 100;
  const momentumAnchor = windowCandles[Math.max(0, windowCandles.length - Math.min(4, windowCandles.length))];
  const recentPct = momentumAnchor.close > 0 ? (last.close - momentumAnchor.close) / momentumAnchor.close * 100 : 0;
  const momentum = Math.tanh(recentPct / Math.max(config.scalePct * 0.46, 0.04)) * 100;
  const trendPct = regressionTrendPct(windowCandles);
  const trend = Math.tanh(trendPct / Math.max(config.scalePct, 0.05)) * 100;
  const score = clamp(price * 0.42 + body * 0.18 + momentum * 0.22 + trend * 0.18, -100, 100);
  return { symbol, score, returnPct, price, candles: body, momentum, trend };
}

async function symbolPressure(symbol: string, config: FrameConfig) {
  const url = new URL(`${ASTER}/fapi/v1/klines`);
  url.searchParams.set("symbol", symbol);
  url.searchParams.set("interval", config.interval);
  url.searchParams.set("limit", String(config.limit));
  const candles = parseCandles(await jsonFetch(url.toString()));
  return analyze(symbol, candles, config);
}

async function mapLimit<T, R>(items: T[], limit: number, worker: (item: T) => Promise<R>): Promise<R[]> {
  const output = new Array<R>(items.length);
  let cursor = 0;
  const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (true) {
      const index = cursor;
      cursor += 1;
      if (index >= items.length) return;
      output[index] = await worker(items[index]);
    }
  });
  await Promise.all(runners);
  return output;
}

export async function GET(request: Request) {
  const authorization = request.headers.get("authorization") || "";
  if (!authorization.startsWith("Bearer ")) return Response.json({ detail: "Firebase ID-token ontbreekt" }, { status: 401 });
  const url = new URL(request.url);
  const timeframe = (url.searchParams.get("timeframe") || "15m") as Timeframe;
  const config = FRAMES[timeframe];
  if (!config) return Response.json({ detail: "Ongeldig Portfolio Impact-timeframe" }, { status: 422 });

  try {
    const symbols = parseSymbols(url.searchParams.get("symbols") || "");
    const cacheKey = `${timeframe}|${[...symbols].sort().join(",")}`;
    const cached = cache.get(cacheKey);
    if (cached && cached.expiresAt > Date.now()) return Response.json(cached.value, { headers: { "Cache-Control": "private, no-store" } });

    const settled = await mapLimit(symbols, 4, async (symbol) => {
      try { return await symbolPressure(symbol, config); }
      catch { return null; }
    });
    const rows = settled.filter((row): row is SymbolPressure => Boolean(row));
    if (rows.length < 3) throw new Error("Onvoldoende realtime Aster-candles voor een betrouwbare marktdrukscore");

    const average = (key: keyof Pick<SymbolPressure, "score" | "price" | "candles" | "momentum" | "trend">) => rows.reduce((sum, row) => sum + row[key], 0) / rows.length;
    const up = rows.filter((row) => row.returnPct > 0.002).length;
    const down = rows.filter((row) => row.returnPct < -0.002).length;
    const flat = rows.length - up - down;
    const breadth = (up - down) / rows.length * 100;
    const aggregateScore = clamp(average("score") * 0.82 + breadth * 0.18, -100, 100);
    const presentation = dominancePresentation(aggregateScore);
    const value = {
      timeframe,
      score: presentation.score,
      longShare: presentation.longShare,
      shortShare: presentation.shortShare,
      stateIndex: presentation.stateIndex,
      status: presentation.status,
      barLabel: presentation.barLabel,
      symbolsUsed: rows.map((row) => row.symbol),
      breadth: { up, down, flat },
      components: {
        price: Math.round(average("price")),
        candles: Math.round(average("candles")),
        momentum: Math.round(average("momentum")),
        trend: Math.round(average("trend")),
        breadth: Math.round(breadth),
      },
      deterministic: true,
      readOnly: true,
      updatedAt: Date.now(),
    };
    cache.set(cacheKey, { expiresAt: Date.now() + config.ttlMs, value });
    return Response.json(value, { headers: { "Cache-Control": "private, no-store" } });
  } catch (reason) {
    const detail = reason instanceof Error ? reason.message : "Portfolio Impact-marktdruk kon niet worden berekend";
    return Response.json({ detail }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
