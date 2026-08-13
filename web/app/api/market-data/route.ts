import { NextRequest, NextResponse } from "next/server";

const allowedIntervals = new Set(["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "1w"]);

function cleanSymbol(value: string) {
  return value.toUpperCase().replace(/[^A-Z0-9]/g, "").replace(/USDT$/, "");
}

export async function GET(request: NextRequest) {
  const exchange = request.nextUrl.searchParams.get("exchange") === "hyperliquid" ? "hyperliquid" : "aster";
  const symbol = cleanSymbol(request.nextUrl.searchParams.get("symbol") || "BTC");
  const interval = (request.nextUrl.searchParams.get("interval") || "15m").toLowerCase();
  const limit = Math.min(1000, Math.max(100, Number(request.nextUrl.searchParams.get("limit") || 600)));
  const before = Number(request.nextUrl.searchParams.get("before") || Date.now());
  if (!allowedIntervals.has(interval)) return NextResponse.json({ error: "Dit timeframe wordt niet ondersteund." }, { status: 400 });

  try {
    if (exchange === "aster") {
      const market = `${symbol}USDT`;
      const url = new URL("https://fapi.asterdex.com/fapi/v1/klines");
      url.searchParams.set("symbol", market);
      url.searchParams.set("interval", interval);
      url.searchParams.set("limit", String(limit));
      url.searchParams.set("endTime", String(before));
      const response = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(12_000) });
      if (!response.ok) throw new Error(`Aster market data ${response.status}`);
      const rows = await response.json() as unknown[][];
      return NextResponse.json({
        exchange, symbol: market, source: "Aster Futures", interval,
        candles: rows.map((row) => ({ time: Math.floor(Number(row[0]) / 1000), open: Number(row[1]), high: Number(row[2]), low: Number(row[3]), close: Number(row[4]), volume: Number(row[5]) })),
      });
    }

    const intervalMs: Record<string, number> = { "1m": 60e3, "3m": 180e3, "5m": 300e3, "15m": 900e3, "30m": 1800e3, "1h": 3600e3, "2h": 7200e3, "4h": 14400e3, "6h": 21600e3, "12h": 43200e3, "1d": 86400e3, "1w": 604800e3 };
    const response = await fetch("https://api.hyperliquid.xyz/info", {
      method: "POST", headers: { "content-type": "application/json" }, cache: "no-store", signal: AbortSignal.timeout(12_000),
      body: JSON.stringify({ type: "candleSnapshot", req: { coin: symbol, interval, startTime: before - intervalMs[interval] * limit, endTime: before } }),
    });
    if (!response.ok) throw new Error(`Hyperliquid market data ${response.status}`);
    const rows = await response.json() as Array<Record<string, unknown>>;
    return NextResponse.json({
      exchange, symbol, source: "Hyperliquid", interval,
      candles: rows.map((row) => ({ time: Math.floor(Number(row.t) / 1000), open: Number(row.o), high: Number(row.h), low: Number(row.l), close: Number(row.c), volume: Number(row.v) })),
    });
  } catch (reason) {
    return NextResponse.json({ error: reason instanceof Error ? reason.message : "Marktdata is tijdelijk niet beschikbaar." }, { status: 502 });
  }
}
