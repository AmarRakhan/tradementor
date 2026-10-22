import { NextResponse } from "next/server";
import { CMC_PUBLIC_GLOBAL_METRICS_URL, CMC_WEBSITE_GLOBAL_METRICS_URL, parseMarketCapChange, type MarketCapChange } from "@/lib/market-cap-change.mjs";

// Build 607: CoinMarketCap totale market cap 24u-verandering voor Portfolio Snapshot.
// Openbare marktdata, geen account- of tradinggegevens. Eén ophaalactie per minuut per instance.

const CACHE_MS = 60_000;
let cached: { at: number; value: MarketCapChange } | null = null;
let inFlight: Promise<MarketCapChange | null> | null = null;

async function fetchFrom(url: string) {
  const response = await fetch(url, {
    cache: "no-store",
    headers: { accept: "application/json", "user-agent": "Mozilla/5.0 (Tradementor market overview)" },
    signal: AbortSignal.timeout(8_000),
  });
  if (!response.ok) throw new Error(`CoinMarketCap ${response.status}`);
  return parseMarketCapChange(await response.json());
}

async function load(): Promise<MarketCapChange | null> {
  for (const url of [CMC_PUBLIC_GLOBAL_METRICS_URL, CMC_WEBSITE_GLOBAL_METRICS_URL]) {
    try {
      const value = await fetchFrom(url);
      if (value) return value;
    } catch {
      // volgende bron proberen
    }
  }
  return null;
}

export async function GET() {
  const now = Date.now();
  if (!cached || now - cached.at >= CACHE_MS) {
    inFlight ??= load().finally(() => { inFlight = null; });
    const fresh = await inFlight;
    if (fresh) cached = { at: Date.now(), value: fresh };
  }
  if (!cached) return NextResponse.json({ error: "CoinMarketCap is tijdelijk niet bereikbaar." }, { status: 502, headers: { "cache-control": "no-store" } });
  return NextResponse.json({
    source: "CoinMarketCap",
    marketCap: cached.value,
    fetchedAt: new Date(cached.at).toISOString(),
    stale: Date.now() - cached.at > CACHE_MS * 5,
  }, { headers: { "cache-control": "no-store" } });
}
