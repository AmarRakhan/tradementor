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
  // Close Profits 2.1: in-page model of the SERVER round (one active round, one item per advance). The per-item close
  // uses the same in-page close model as the individual route below. __offline makes requests fail like a phone that
  // lost its connection (nothing reaches the "server").
  if (path.startsWith("/api/exchanges/aster/profit-close-rounds")) {
    if (w.__offline) throw new TypeError("Failed to fetch");
    w.__rounds = w.__rounds || {};
    const view = (r: any) => {
      const c = { total: r.items.length, done: 0, skipped: 0, needsCheck: 0, remaining: 0 };
      for (const i of r.items) {
        if (i.status === "DONE") c.done++; else if (i.status === "SKIPPED") c.skipped++;
        else if (i.status === "NEEDS_CHECK") c.needsCheck++; else c.remaining++;
      }
      return JSON.parse(JSON.stringify({ ...r, counts: c }));
    };
    const open = (r: any) => r && (r.status === "RUNNING" || r.status === "PAUSED");
    if (path.endsWith("/active")) return { round: open(w.__rounds[w.__activeRound]) ? view(w.__rounds[w.__activeRound]) : null };
    if (path === "/api/exchanges/aster/profit-close-rounds" && method === "POST") {
      if (open(w.__rounds[w.__activeRound])) throw new Error("Er loopt nog een Close Profits-ronde; hervat of sluit die eerst af");
      const id = ("a" + Object.keys(w.__rounds).length).padEnd(24, "0");
      w.__rounds[id] = { roundId: id, status: "RUNNING", percentage: body.percentage,
        items: body.targets.map((t: any) => ({ symbol: t.symbol, side: "SHORT", expectedQuantity: t.quantity, status: "PENDING", attempt: 0 })) };
      w.__activeRound = id;
      return { created: true, round: view(w.__rounds[id]) };
    }
    const m = path.match(/profit-close-rounds\/([a-f0-9]+)\/(advance|resume|abandon)$/);
    const r = m && w.__rounds[m[1]];
    if (!r) throw new Error("Ronde niet gevonden");
    if (m![2] === "abandon") { r.status = "ABANDONED"; w.__activeRound = ""; return { round: view(r), pending: false }; }
    if (m![2] === "resume") { if (r.status === "PAUSED") r.status = "RUNNING"; return { round: view(r) }; }
    const item = r.items.find((i: any) => !["DONE", "SKIPPED", "NEEDS_CHECK"].includes(i.status));
    if (r.status === "RUNNING" && item) {
      const pos = (w.__world as Pos[]).find((p) => p.symbol === item.symbol && p.side === "SHORT");
      if (w.__fail[item.symbol]) item.status = "NEEDS_CHECK";
      else if (!pos || Math.abs(pos.qty - item.expectedQuantity) > 1e-9) item.status = "SKIPPED";
      else if (!(pnl(pos) > 0.5)) item.status = "SKIPPED";
      else {
        const closed = pos.qty * r.percentage / 100;
        pos.qty -= closed;
        item.status = "DONE";
        w.__closes = w.__closes || [];
        w.__closes.push({ symbol: item.symbol, closed, expected: item.expectedQuantity, percentage: r.percentage });
      }
      if (typeof w.__offlineAfterCloses === "number" && (w.__closes || []).length >= w.__offlineAfterCloses) w.__offline = true;
    }
    if (!r.items.some((i: any) => !["DONE", "SKIPPED", "NEEDS_CHECK"].includes(i.status)) && r.status === "RUNNING") {
      r.status = "FINISHED"; w.__activeRound = "";
    }
    return { round: view(r), busy: false, waiting: false };
  }
  // Re-Hedge All 1.0: in-page model of the Auto Hedge state + the single bulk endpoint (the server decides sizes).
  if (path === "/api/exchanges/aster/position-loss-auto-hedge" && method === "GET") {
    return { enabled: w.__autoHedgeOff ? false : true, pairs: (w.__ahPairs || []).map((p: any) => ({ ...p })) };
  }
  if (path === "/api/exchanges/aster/position-loss-auto-hedge/rehedge-all" && method === "POST") {
    if (w.__rehedgeFail) throw new Error(w.__rehedgeFail);
    const recovery = (w.__ahPairs || []).filter((p: any) => ["RECOVERY", "REHEDGE_ARMED", "DISABLED"].includes(p.status));
    const items = recovery.map((p: any) => {
      p.status = "HEDGED";
      return { symbol: p.symbol, outcome: "PROTECTED", longNotional: p.long, shortNotionalBefore: p.short,
        shortNotionalAfter: p.long, hedgePercent: 100, addedShortQty: 1 };
    });
    return { rehedgeAll: { status: items.length ? "DONE" : "NOTHING_TO_DO", mode: "LIVE", found: items.length, ordersSent: items.length, items } };
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
