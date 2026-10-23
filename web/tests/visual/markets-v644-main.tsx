import { createRoot } from "react-dom/client";
import { MarketsPage } from "../../components/markets-page";
import { publishAsterPositions } from "../../lib/aster-positions-feed";
import "../../app/portfolio-koers-chart.css";

// Fake candles for /api/market-data: a smooth random walk around the live price.
const realFetch = window.fetch.bind(window);
window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = new URL(String(input instanceof Request ? input.url : input), window.location.href);
  if (url.pathname === "/api/market-data") {
    const limit = Number(url.searchParams.get("limit") || 500);
    const step = ({ "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400 } as Record<string, number>)[url.searchParams.get("interval") || "15m"] || 900;
    const now = Math.floor(Date.now() / 1000 / step) * step;
    let price = 81300, seed = 7;
    const rnd = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };
    const candles = [];
    for (let index = 0; index < Math.min(limit, 300); index += 1) {
      const open = price, close = open + (rnd() - 0.5) * 160;
      candles.push({ time: now - (Math.min(limit, 300) - 1 - index) * step, open, high: Math.max(open, close) + rnd() * 60, low: Math.min(open, close) - rnd() * 60, close, volume: 1 });
      price = close;
    }
    return new Response(JSON.stringify({ candles }), { headers: { "content-type": "application/json" } });
  }
  return realFetch(input, init);
};

publishAsterPositions([
  { symbol: "NVDAUSDT", side: "LONG", strategyId: "aster-strategy-2", quantity: 1 },
  { symbol: "BTCUSDT", side: "LONG", strategyId: "aster-strategy-2", quantity: 0.004 },
  { symbol: "BTCUSDT", side: "SHORT", strategyId: "", positionLossAutoHedge: { status: "HEDGED" }, quantity: 0.004 },
  { symbol: "SOLUSDT", side: "LONG", strategyId: "", quantity: 3 },
  { symbol: "XRPUSDT", side: "LONG", strategyId: "aster-strategy-2", quantity: 10 },
  { symbol: "BNBUSDT", side: "LONG", strategyId: "aster-strategy-2", quantity: 1 },
]);

createRoot(document.getElementById("root")!).render(<div className="content"><div className="markets-portal"><MarketsPage /></div></div>);
