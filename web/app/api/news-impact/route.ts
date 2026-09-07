type Candle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

type WindowKey = "1m" | "5m" | "15m" | "1u" | "4u" | "24u";

const WINDOW_MS: Record<WindowKey, number> = {
  "1m": 60_000,
  "5m": 300_000,
  "15m": 900_000,
  "1u": 3_600_000,
  "4u": 14_400_000,
  "24u": 86_400_000,
};

const impactCache = new Map<string, { expiresAt: number; value: Record<string, unknown> }>();

function cleanSymbol(value: unknown) {
  return String(value || "")
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "")
    .replace(/(USDT|USDC|USD|PERP)$/i, "")
    .replace(/^1000(?=[A-Z])/, "");
}

function round(value: number | null, digits = 4) {
  if (value === null || !Number.isFinite(value)) return null;
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function pct(from: number, to: number) {
  if (!Number.isFinite(from) || !Number.isFinite(to) || from <= 0) return null;
  return ((to - from) / from) * 100;
}

async function fetchKlines(market: string, interval: "1m" | "5m", startTime?: number, endTime?: number, limit = 300) {
  const url = new URL("https://fapi.asterdex.com/fapi/v1/klines");
  url.searchParams.set("symbol", market);
  url.searchParams.set("interval", interval);
  url.searchParams.set("limit", String(Math.max(1, Math.min(1000, limit))));
  if (Number.isFinite(startTime)) url.searchParams.set("startTime", String(Math.floor(startTime!)));
  if (Number.isFinite(endTime)) url.searchParams.set("endTime", String(Math.floor(endTime!)));
  const response = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(9_000) });
  if (!response.ok) throw new Error(`Aster marktdata ${response.status}`);
  const rows = await response.json() as unknown[][];
  return rows.map((row) => ({
    time: Number(row[0]),
    open: Number(row[1]),
    high: Number(row[2]),
    low: Number(row[3]),
    close: Number(row[4]),
    volume: Number(row[5]),
  })).filter((row) => Number.isFinite(row.time) && Number.isFinite(row.close) && row.close > 0);
}

async function resolveMarket(symbol: string, publishedAt: number, now: number) {
  const candidates = [`${symbol}USDT`];
  if (["SHIB", "PEPE", "FLOKI", "BONK"].includes(symbol)) candidates.push(`1000${symbol}USDT`);
  let lastError: unknown = null;
  for (const market of candidates) {
    try {
      const probe = await fetchKlines(market, "1m", Math.max(0, publishedAt - 2 * 60_000), Math.min(now, publishedAt + 2 * 60_000), 8);
      if (probe.length) return market;
    } catch (reason) {
      lastError = reason;
    }
  }
  throw lastError instanceof Error ? lastError : new Error("Geen Aster-markt voor deze munt gevonden.");
}

function nearest(candles: Candle[], target: number) {
  if (!candles.length) return null;
  let best = candles[0];
  let distance = Math.abs(best.time - target);
  for (const candle of candles.slice(1)) {
    const next = Math.abs(candle.time - target);
    if (next < distance) {
      best = candle;
      distance = next;
    }
  }
  return best;
}

function average(values: number[]) {
  const clean = values.filter(Number.isFinite);
  return clean.length ? clean.reduce((sum, value) => sum + value, 0) / clean.length : null;
}

function reactionLabel(changePercent: number | null) {
  if (changePercent === null) return "Onbekend";
  if (changePercent >= 0.5) return "Positief";
  if (changePercent <= -0.5) return "Negatief";
  return "Neutraal";
}

function expectedLabel(sentiment: string) {
  if (sentiment === "bullish") return "Positief";
  if (sentiment === "bearish") return "Negatief";
  return "Gemengd";
}

function volatilityLabel(rangePercent: number | null) {
  if (rangePercent === null) return "Onbekend";
  if (rangePercent >= 3) return "Hoog";
  if (rangePercent >= 1.1) return "Normaal";
  return "Laag";
}

function momentumLabel(changePercent: number | null) {
  if (changePercent === null) return "Onbekend";
  if (changePercent > 0.18) return "Oplopend";
  if (changePercent < -0.18) return "Afnemend";
  return "Afwachtend";
}

function pricedInLabel(ageMs: number, measured: number | null, momentum: number | null, volumeRatio: number | null) {
  if (ageMs < 10 * 60_000) return "Reactie is nog bezig";
  if (measured !== null && Math.abs(measured) < 0.25) return "Koers heeft nog nauwelijks gereageerd";
  if (ageMs >= 60 * 60_000 && measured !== null && Math.abs(measured) >= 0.6 && momentum !== null && Math.abs(momentum) < 0.12) {
    return "Waarschijnlijk grotendeels ingeprijsd";
  }
  if (volumeRatio !== null && volumeRatio >= 1.6 && measured !== null && Math.abs(measured) >= 0.8) return "Waarschijnlijk deels ingeprijsd";
  return "Onzeker — reactie kan nog doorlopen";
}

function cachePut(key: string, value: Record<string, unknown>) {
  impactCache.set(key, { expiresAt: Date.now() + 90_000, value });
  if (impactCache.size > 300) {
    const first = impactCache.keys().next().value as string | undefined;
    if (first) impactCache.delete(first);
  }
}

export async function GET(request: Request) {
  const incoming = new URL(request.url);
  const symbol = cleanSymbol(incoming.searchParams.get("symbol"));
  const publishedAtRaw = incoming.searchParams.get("publishedAt") || "";
  const sentiment = String(incoming.searchParams.get("sentiment") || "neutral").toLowerCase();
  const publishedAt = Date.parse(publishedAtRaw);
  const now = Date.now();

  if (!symbol || symbol === "MACRO") {
    return Response.json({ ok: true, available: false, reason: "Voor macro-nieuws is geen enkele munt als koersreferentie beschikbaar." });
  }
  if (!Number.isFinite(publishedAt)) {
    return Response.json({ ok: false, available: false, reason: "Ongeldig publicatiemoment." }, { status: 400 });
  }

  const cacheKey = `${symbol}:${Math.floor(publishedAt / 60_000)}:${Math.floor(now / 60_000)}`;
  const cached = impactCache.get(cacheKey);
  if (cached && cached.expiresAt > now) return Response.json(cached.value, { headers: { "Cache-Control": "private, max-age=60" } });

  try {
    const market = await resolveMarket(symbol, publishedAt, now);
    const microStart = Math.max(0, publishedAt - 15 * 60_000);
    const microEnd = Math.min(now, publishedAt + 60 * 60_000);
    const macroEnd = Math.min(now, publishedAt + 24 * 60 * 60_000);
    const latestStart = Math.max(0, now - 45 * 60_000);

    const [micro, macro, latest] = await Promise.all([
      fetchKlines(market, "1m", microStart, microEnd, 90),
      fetchKlines(market, "5m", microStart, macroEnd, 320),
      fetchKlines(market, "5m", latestStart, now, 12),
    ]);

    const publicationCandle = nearest(micro, publishedAt) || nearest(macro, publishedAt);
    if (!publicationCandle) throw new Error("Geen koers rond het publicatiemoment beschikbaar.");

    const publicationPrice = publicationCandle.close;
    const currentPrice = latest.at(-1)?.close ?? macro.at(-1)?.close ?? micro.at(-1)?.close ?? publicationPrice;
    const ageMs = Math.max(0, now - publishedAt);
    const observed = macro.filter((row) => row.time >= publishedAt && row.time <= macroEnd);
    const observedFallback = micro.filter((row) => row.time >= publishedAt && row.time <= microEnd);
    const observedRows = observed.length ? observed : observedFallback;
    const highPrice = observedRows.length ? Math.max(...observedRows.map((row) => row.high)) : publicationPrice;
    const lowPrice = observedRows.length ? Math.min(...observedRows.map((row) => row.low)) : publicationPrice;
    const currentChange = pct(publicationPrice, currentPrice);
    const highChange = pct(publicationPrice, highPrice);
    const lowChange = pct(publicationPrice, lowPrice);

    const beforeVolumes = macro.filter((row) => row.time >= publishedAt - 15 * 60_000 && row.time < publishedAt).map((row) => row.volume);
    const afterVolumes = macro.filter((row) => row.time >= publishedAt && row.time < publishedAt + 15 * 60_000).map((row) => row.volume);
    const beforeVolume = average(beforeVolumes);
    const afterVolume = average(afterVolumes);
    const volumeRatio = beforeVolume && afterVolume !== null ? afterVolume / beforeVolume : null;
    const volumeLabel = volumeRatio === null ? "Onbekend" : volumeRatio >= 1.5 ? "Hoog" : volumeRatio <= 0.72 ? "Laag" : "Normaal";

    const momentumChange = latest.length >= 2 ? pct(latest[0].close, latest.at(-1)!.close) : null;
    const rangePercent = publicationPrice > 0 ? ((highPrice - lowPrice) / publicationPrice) * 100 : null;

    const windows = Object.fromEntries((Object.entries(WINDOW_MS) as Array<[WindowKey, number]>).map(([key, duration]) => {
      const target = publishedAt + duration;
      if (now < target) return [key, { available: false, changePercent: null, price: null, label: "Nog niet beschikbaar" }];
      const source = duration <= 15 * 60_000 ? micro : macro;
      const candle = nearest(source, target);
      if (!candle) return [key, { available: false, changePercent: null, price: null, label: "Niet beschikbaar" }];
      const changePercent = pct(publicationPrice, candle.close);
      return [key, { available: true, changePercent: round(changePercent, 3), price: round(candle.close, 8), label: reactionLabel(changePercent) }];
    }));

    const chartSource = ageMs <= 90 * 60_000 ? micro : macro;
    const chart = chartSource
      .filter((row) => row.time >= microStart && row.time <= macroEnd)
      .slice(-320)
      .map((row) => ({ time: row.time, close: round(row.close, 8) }));

    const value: Record<string, unknown> = {
      ok: true,
      available: true,
      symbol,
      market,
      source: "Aster Futures",
      publishedAt: new Date(publishedAt).toISOString(),
      observedUntil: new Date(macroEnd).toISOString(),
      observationCappedAt24h: now > publishedAt + 24 * 60 * 60_000,
      publicationPrice: round(publicationPrice, 8),
      currentPrice: round(currentPrice, 8),
      changePercent: round(currentChange, 3),
      highPrice: round(highPrice, 8),
      highPercent: round(highChange, 3),
      lowPrice: round(lowPrice, 8),
      lowPercent: round(lowChange, 3),
      expectedImpact: expectedLabel(sentiment),
      measuredReaction: reactionLabel(currentChange),
      momentum: momentumLabel(momentumChange),
      momentumPercent: round(momentumChange, 3),
      volatility: volatilityLabel(rangePercent),
      volatilityRangePercent: round(rangePercent, 3),
      volume: volumeLabel,
      volumeRatio: round(volumeRatio, 2),
      pricedIn: pricedInLabel(ageMs, currentChange, momentumChange, volumeRatio),
      windows,
      chart,
    };
    cachePut(cacheKey, value);
    return Response.json(value, { headers: { "Cache-Control": "private, max-age=60" } });
  } catch (reason) {
    return Response.json({
      ok: true,
      available: false,
      symbol,
      reason: reason instanceof Error ? reason.message : "Koersreactie is tijdelijk niet beschikbaar.",
    }, { headers: { "Cache-Control": "private, max-age=30" } });
  }
}
