// In-page fake of lib/cloud-client for the Close Profits UI test. No network, no Firebase.
type Pos = { symbol: string; side: "SHORT" | "LONG"; qty: number; entry: number; mark: number; hedged?: boolean };
const w = window as any;
w.__calls = [] as Array<{ method: string; path: string; body: any }>;
w.__fail = {} as Record<string, string>;
w.__delay = 0;
w.__world = [
  { symbol: "BTCUSDT", side: "SHORT", qty: 2, entry: 105, mark: 100 },
  { symbol: "ETHUSDT", side: "SHORT", qty: 10, entry: 105, mark: 100, hedged: true },
  { symbol: "SOLUSDT", side: "SHORT", qty: 100, entry: 105, mark: 100 },
  { symbol: "XRPUSDT", side: "SHORT", qty: 500, entry: 105, mark: 100, hedged: true },
  { symbol: "DOGEUSDT", side: "SHORT", qty: 50, entry: 95, mark: 100 },     // losing SHORT: never selected
  { symbol: "ADAUSDT", side: "LONG", qty: 40, entry: 90, mark: 100 },        // profitable LONG: never selected
] as Pos[];
const pnl = (p: Pos) => (p.side === "SHORT" ? p.entry - p.mark : p.mark - p.entry) * p.qty;
w.__pnl = pnl;

export async function authenticatedRequest(path: string, init: RequestInit = {}) {
  const method = String(init.method || "GET").toUpperCase();
  const body = init.body ? JSON.parse(String(init.body)) : null;
  w.__calls.push({ method, path, body });
  if (w.__delay) await new Promise((resolve) => setTimeout(resolve, w.__delay));
  if (path.startsWith("/api/exchanges/aster/positions/manual-profit-close-plan")) {
    const rows = (w.__world as Pos[]).filter((p) => p.qty > 0);
    return {
      reliable: true,
      selected: rows.filter((p) => pnl(p) > 0.5).map((p) => ({ symbol: p.symbol, side: p.side })),
      skipped: [],
      snapshot: { rows: rows.map((p) => ({ symbol: p.symbol, side: p.side, quantity: String(p.qty), unrealizedPnl: String(pnl(p)) })), csv: "symbol,side\n" },
    };
  }
  const match = path.match(/\/positions\/([^/]+)\/close$/);
  if (match && method === "POST") {
    const symbol = decodeURIComponent(match[1]);
    if (w.__fail[symbol]) throw new Error(w.__fail[symbol]);
    const pos = (w.__world as Pos[]).find((p) => p.symbol === symbol && p.side === body.side);
    if (!pos || Math.abs(pos.qty - body.expected_quantity) > 1e-9) throw new Error("De positiegrootte is gewijzigd; controleer de actuele positie en bevestig opnieuw");
    const closed = pos.qty * body.percentage / 100;
    pos.qty -= closed;
    return { closed: pos.qty <= 0, closedSize: closed, remainingSize: pos.qty, autoHedgeStatus: pos.hedged ? "RECOVERY" : null };
  }
  return {};
}
export async function authenticatedStream() {
  throw new Error("streams are not available in the UI test");
}
