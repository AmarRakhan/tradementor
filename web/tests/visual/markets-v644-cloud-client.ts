// In-page fake of lib/cloud-client for the Markets 644 visual QA. No network, no Firebase.
import fixture from "./markets-v644-fixture.json";

const LEVERAGE: Record<string, number> = { BTCUSDT: 200, ETHUSDT: 200, SOLUSDT: 100, XRPUSDT: 75, DOGEUSDT: 75, ADAUSDT: 75, BNBUSDT: 125, LTCUSDT: 75, TRXUSDT: 75, LINKUSDT: 75, "1000PEPEUSDT": 50, IRYSUSDT: 10 };
const w = window as any;
w.__calls = [] as string[];

function bbFor(symbol: string, index: number) {
  const row = (fixture as any[]).find((item) => item.symbol === symbol);
  const price = Number(row?.lastPrice || 1);
  const pick = index % 3;
  const upper = pick === 0 ? price * 0.99 : price * 1.01;
  const lower = pick === 2 ? price * 1.01 : price * 0.99;
  return { upper, lower, middle: (upper + lower) / 2, status: pick === 0 ? "above" : pick === 2 ? "below" : "between" };
}

export async function authenticatedRequest(path: string) {
  w.__calls.push(path);
  const url = new URL(path, "http://qa.local");
  if (url.pathname === "/api/markets/aster" && url.searchParams.get("mode") === "base") {
    return { exchange: "aster", interval: url.searchParams.get("interval") || "15m", marketCount: (fixture as any[]).length, updatedAt: Date.now(), markets: fixture };
  }
  if (url.pathname === "/api/markets/aster" && url.searchParams.get("mode") === "enrich") {
    await new Promise((resolve) => setTimeout(resolve, 40));
    const symbols = String(url.searchParams.get("symbols") || "").split(",");
    return { markets: symbols.map((symbol) => { const index = (fixture as any[]).findIndex((row) => row.symbol === symbol); const bb = bbFor(symbol, index); return { symbol, maxLeverage: LEVERAGE[symbol] || 20, bbStatus: bb.status, bbUpper: bb.upper, bbMiddle: bb.middle, bbLower: bb.lower }; }), errors: [], updatedAt: Date.now() };
  }
  if (url.pathname === "/api/exchanges/aster/trade-events") {
    const side = url.searchParams.get("side");
    const now = Date.now();
    if (url.searchParams.get("symbol") !== "BTCUSDT") return { events: [] };
    const base = 81300;
    const ev = (minutesAgo: number, action: string, price: number, quantity = 0.004) => ({ id: `${side}-${minutesAgo}`, side, kind: action === "increase" ? "entry" : "close", action, price, quantity, timestampMs: now - minutesAgo * 60_000, at: "" });
    return side === "LONG"
      ? { events: [ev(600, "increase", base - 120), ev(420, "close", base + 260), ev(300, "increase", base - 60), ev(120, "close", base + 90)] }
      : { events: [ev(240, "increase", base + 40), ev(90, "close", base - 150)] };
  }
  throw new Error(`QA: geen nep-antwoord voor ${path}`);
}
