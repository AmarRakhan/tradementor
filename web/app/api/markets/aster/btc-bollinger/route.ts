const ASTER = "https://fapi.asterdex.com";
const SYMBOL = "BTCUSDT";
const PERIOD = 20;
const DEVIATIONS = 2;
const ALLOWED_INTERVALS = new Set(["1m", "5m", "15m", "1h", "4h", "1d"]);
const CACHE_TTL_MS: Record<string, number> = {
  "1m": 10_000,
  "5m": 15_000,
  "15m": 20_000,
  "1h": 30_000,
  "4h": 60_000,
  "1d": 120_000,
};

type Snapshot = {
  symbol: string;
  interval: string;
  price: number;
  lower: number;
  middle: number;
  upper: number;
  score: number;
  updatedAt: number;
};

type CachedSnapshot = { expiresAt: number; value: Snapshot };
const cache = new Map<string, CachedSnapshot>();

function finite(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function calculate(closes: number[], price: number, interval: string): Snapshot {
  const sample = closes.slice(-PERIOD);
  if (sample.length < PERIOD || sample.some((value) => !Number.isFinite(value) || value <= 0)) {
    throw new Error("Onvoldoende geldige BTC-candles voor Bollinger Bands");
  }
  const middle = sample.reduce((sum, value) => sum + value, 0) / sample.length;
  const variance = sample.reduce((sum, value) => sum + ((value - middle) ** 2), 0) / sample.length;
  const deviation = Math.sqrt(variance);
  const upper = middle + DEVIATIONS * deviation;
  const lower = middle - DEVIATIONS * deviation;
  if (!(upper > lower)) throw new Error("BTC Bollinger-bandbreedte is ongeldig");
  const score = Math.max(0, Math.min(100, ((price - lower) / (upper - lower)) * 100));
  return { symbol: SYMBOL, interval, price, lower, middle, upper, score, updatedAt: Date.now() };
}

async function fetchJson(url: string) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10_000);
  try {
    const response = await fetch(url, { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error(`Aster HTTP ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

async function loadSnapshot(interval: string) {
  const cached = cache.get(interval);
  if (cached && cached.expiresAt > Date.now()) return cached.value;

  const klinesUrl = new URL(`${ASTER}/fapi/v1/klines`);
  klinesUrl.searchParams.set("symbol", SYMBOL);
  klinesUrl.searchParams.set("interval", interval);
  klinesUrl.searchParams.set("limit", String(PERIOD));

  const tickerUrl = new URL(`${ASTER}/fapi/v1/ticker/price`);
  tickerUrl.searchParams.set("symbol", SYMBOL);

  const [klinesPayload, tickerPayload] = await Promise.all([
    fetchJson(klinesUrl.toString()),
    fetchJson(tickerUrl.toString()),
  ]);

  if (!Array.isArray(klinesPayload)) throw new Error("BTC candle-response heeft een ongeldig formaat");
  const closes = klinesPayload.map((row) => Array.isArray(row) ? finite(row[4]) ?? 0 : 0);
  const ticker = tickerPayload && typeof tickerPayload === "object" ? tickerPayload as Record<string, unknown> : null;
  const livePrice = finite(ticker?.price) ?? closes.at(-1) ?? null;
  if (livePrice === null || livePrice <= 0) throw new Error("Actuele BTC-prijs ontbreekt");

  const snapshot = calculate(closes, livePrice, interval);
  cache.set(interval, { expiresAt: Date.now() + (CACHE_TTL_MS[interval] ?? 15_000), value: snapshot });
  return snapshot;
}

export async function GET(request: Request) {
  const authorization = request.headers.get("authorization") || "";
  if (!authorization.startsWith("Bearer ")) {
    return Response.json({ detail: "Firebase ID-token ontbreekt" }, { status: 401, headers: { "Cache-Control": "no-store" } });
  }

  const url = new URL(request.url);
  const interval = url.searchParams.get("interval") || "15m";
  if (!ALLOWED_INTERVALS.has(interval)) {
    return Response.json({ detail: "Ongeldig BTC Bollinger-timeframe" }, { status: 422, headers: { "Cache-Control": "no-store" } });
  }

  try {
    const snapshot = await loadSnapshot(interval);
    return Response.json(snapshot, { headers: { "Cache-Control": "private, no-store" } });
  } catch (reason) {
    const detail = reason instanceof Error ? reason.message : "BTC Bollinger-data tijdelijk niet beschikbaar";
    return Response.json({ detail }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
