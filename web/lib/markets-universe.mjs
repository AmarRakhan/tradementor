// Build 640: Markets = every Aster perpetual that is tradable right now,
// whatever it settles in (USDT, USD1, USDC, U). Pure helpers, shared by the
// server route, the Markets page and the tests.

export const MARKET_CATEGORIES = Object.freeze(["crypto", "stock", "commodity"]);
export const MARKET_OWNER_FILTERS = Object.freeze(["all", "free", "position", "bot", "manual"]);
export const MARKET_BB_TIMEFRAMES = Object.freeze(["1m", "5m", "15m", "1h", "4h", "1d"]);
export const MARKET_BB_LABEL = Object.freeze({ "1m": "1m", "5m": "5m", "15m": "15m", "1h": "1u", "4h": "4u", "1d": "1d" });
const BB_RANK = Object.freeze({ above: 3, between: 2, below: 1 });

function finite(value) {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

/** Aster labels its own markets: Commodities, STOCK/ETF; everything else is crypto. */
export function marketCategory(info) {
  const tags = (Array.isArray(info?.underlyingSubType) ? info.underlyingSubType : []).map((value) => String(value).toUpperCase());
  if (tags.includes("COMMODITIES")) return "commodity";
  if (tags.includes("STOCK") || tags.includes("ETF")) return "stock";
  if (Number(info?.symbolType) === 1) return "stock";
  return "crypto";
}

export function isTradablePerpetual(info) {
  const symbol = String(info?.symbol || "").toUpperCase();
  const quote = String(info?.quoteAsset || "").toUpperCase();
  const status = String(info?.status || "").toUpperCase();
  const contract = String(info?.contractType || "PERPETUAL").toUpperCase();
  return Boolean(symbol && quote && /^[A-Z0-9]{2,40}$/.test(symbol)) && status === "TRADING" && (contract === "PERPETUAL" || contract === "");
}

/** One row per tradable perpetual, highest 24h volume first. */
export function buildMarketRows(exchangeInfo, tickers) {
  const tickerBySymbol = new Map((Array.isArray(tickers) ? tickers : [])
    .filter((row) => row && typeof row === "object")
    .map((row) => [String(row.symbol || "").toUpperCase(), row]));
  const rows = [];
  for (const info of Array.isArray(exchangeInfo?.symbols) ? exchangeInfo.symbols : []) {
    if (!info || typeof info !== "object" || !isTradablePerpetual(info)) continue;
    const symbol = String(info.symbol).toUpperCase();
    const ticker = tickerBySymbol.get(symbol) || {};
    const lastPrice = finite(ticker.lastPrice);
    if (lastPrice <= 0) continue;
    rows.push({
      symbol,
      baseAsset: String(info.baseAsset || symbol).toUpperCase(),
      quoteAsset: String(info.quoteAsset || "").toUpperCase(),
      name: String(info.name || "").trim(),
      category: marketCategory(info),
      pricePrecision: Math.max(0, Math.min(10, Math.trunc(finite(info.pricePrecision)) || 2)),
      lastPrice,
      change24hPct: finite(ticker.priceChangePercent),
      high24h: finite(ticker.highPrice),
      low24h: finite(ticker.lowPrice),
      quoteVolume24h: Math.max(0, finite(ticker.quoteVolume)),
      maxLeverage: null,
      bbStatus: null,
      bbUpper: null,
      bbMiddle: null,
      bbLower: null,
    });
  }
  rows.sort((a, b) => b.quoteVolume24h - a.quoteVolume24h || a.symbol.localeCompare(b.symbol));
  return rows;
}

/** BOT = the bot owns the leg (strategy leg or Auto Hedge); MANUAL = an open leg the bot does not own. */
export function ownershipBySymbol(positions) {
  const result = new Map();
  for (const raw of Array.isArray(positions) ? positions : []) {
    if (!raw || typeof raw !== "object") continue;
    const symbol = String(raw.symbol || "").toUpperCase();
    if (!symbol) continue;
    const quantity = raw.quantity ?? raw.positionAmt ?? raw.size ?? raw.notionalUsd;
    if (quantity !== undefined && Math.abs(finite(quantity)) <= 0) continue;
    const bot = String(raw.strategyId || "").trim() !== "" || Boolean(raw.positionLossAutoHedge);
    const current = result.get(symbol) || { bot: false, manual: false };
    if (bot) current.bot = true; else current.manual = true;
    result.set(symbol, current);
  }
  return result;
}

export function bbStatusFor(livePrice, upper, lower, fallback = null) {
  if (upper === null || lower === null || upper === undefined || lower === undefined) return fallback;
  return livePrice > upper ? "above" : livePrice < lower ? "below" : "between";
}

export function filterMarkets(rows, options = {}) {
  const query = String(options.query || "").trim().toUpperCase().replace(/[^A-Z0-9 ]/g, "");
  const owner = options.owner || "all";
  const category = options.category || "all";
  const bb = options.bb || "all";
  const ownership = options.ownership instanceof Map ? options.ownership : new Map();
  const favorites = options.favorites instanceof Set ? options.favorites : new Set();
  return (Array.isArray(rows) ? rows : []).filter((row) => {
    if (query) {
      const haystack = `${row.symbol} ${row.baseAsset} ${String(row.name || "").toUpperCase()}`;
      if (!query.split(/\s+/).every((part) => haystack.includes(part))) return false;
    }
    if (category !== "all" && row.category !== category) return false;
    const own = ownership.get(row.symbol);
    if (owner === "free" && own) return false;
    if (owner === "position" && !own) return false;
    if (owner === "bot" && !own?.bot) return false;
    if (owner === "manual" && !own?.manual) return false;
    if (bb !== "all" && row.bbStatus !== bb) return false;
    if (options.favoritesOnly && !favorites.has(row.symbol)) return false;
    return true;
  });
}

/** key: symbol | volume | bb | change. Rows without BB data always go last. */
export function sortMarkets(rows, key = "change", direction = "desc") {
  const sign = direction === "asc" ? 1 : -1;
  return [...(Array.isArray(rows) ? rows : [])].sort((a, b) => {
    if (key === "symbol") return sign * a.baseAsset.localeCompare(b.baseAsset) || a.symbol.localeCompare(b.symbol);
    if (key === "bb") {
      const ar = a.bbStatus ? BB_RANK[a.bbStatus] : 0, br = b.bbStatus ? BB_RANK[b.bbStatus] : 0;
      if (!ar !== !br) return ar ? -1 : 1;
      return sign * (ar - br) || b.change24hPct - a.change24hPct || a.symbol.localeCompare(b.symbol);
    }
    const delta = key === "volume" ? a.quoteVolume24h - b.quoteVolume24h : a.change24hPct - b.change24hPct;
    return sign * delta || a.symbol.localeCompare(b.symbol);
  });
}

export function compactVolume(value) {
  const amount = Math.max(0, finite(value));
  if (amount >= 1e9) return `${(amount / 1e9).toFixed(2)}B`;
  if (amount >= 1e6) return `${(amount / 1e6).toFixed(2)}M`;
  if (amount >= 1e3) return `${(amount / 1e3).toFixed(2)}K`;
  return amount.toFixed(0);
}

export function signedPercent(value) {
  const amount = finite(value);
  return `${amount > 0 ? "+" : amount < 0 ? "-" : ""}${Math.abs(amount).toFixed(2)}%`;
}

export function formatMarketPrice(value, precision) {
  const amount = finite(value);
  const digits = Number.isFinite(precision) ? Math.max(0, Math.min(10, precision)) : amount >= 1000 ? 2 : amount >= 1 ? 4 : 6;
  return amount.toLocaleString("en-US", { minimumFractionDigits: Math.min(digits, 2), maximumFractionDigits: digits });
}

/** Icon key for public coin icons: 1000PEPE -> pepe, KBONK -> bonk is left as-is. */
export function iconAsset(baseAsset) {
  return String(baseAsset || "").toUpperCase().replace(/^(1000000|100000|10000|1000)(?=[A-Z])/, "").toLowerCase();
}

/**
 * Turn confirmed Aster fills (trade-events, all cycles) into chart labels.
 * A close is a take profit when it beats the cycle's average entry.
 */
export function tradeMarkersFromEvents(events, candleTimes) {
  const times = (Array.isArray(candleTimes) ? candleTimes : []).filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
  if (!times.length) return [];
  const first = times[0];
  const step = times.length > 1 ? Math.max(1, times[1] - times[0]) : 60;
  const bucketOf = (seconds) => {
    if (seconds < first) return null;
    let lo = 0, hi = times.length - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (times[mid] <= seconds) lo = mid; else hi = mid - 1; }
    return seconds - times[lo] <= step * 2 ? times[lo] : null;
  };
  const state = { LONG: { qty: 0, cost: 0 }, SHORT: { qty: 0, cost: 0 } };
  const ordered = [...(Array.isArray(events) ? events : [])]
    .filter((event) => event && (event.side === "LONG" || event.side === "SHORT") && finite(event.price) > 0)
    .sort((a, b) => finite(a.timestampMs) - finite(b.timestampMs));
  const groups = new Map();
  for (const event of ordered) {
    const side = event.side, book = state[side];
    const price = finite(event.price), qty = Math.abs(finite(event.quantity)) || 0;
    let kind = "entry", pnl = 0;
    if (event.action === "increase") {
      book.qty += qty; book.cost += qty * price;
      kind = side === "LONG" ? "long" : "short";
    } else {
      const average = book.qty > 0 ? book.cost / book.qty : price;
      pnl = side === "LONG" ? (price - average) * qty : (average - price) * qty;
      const closed = Math.min(qty, book.qty);
      book.cost -= average * closed; book.qty = Math.max(0, book.qty - closed);
      if (book.qty <= 1e-12) { book.qty = 0; book.cost = 0; }
      kind = pnl > 0 ? "tp" : "exit";
    }
    const time = bucketOf(Math.floor(finite(event.timestampMs) / 1000));
    if (time === null) continue;
    const key = `${time}:${side}:${kind}`;
    const group = groups.get(key) || { time, side, kind, count: 0, pnl: 0 };
    group.count += 1; group.pnl += pnl;
    groups.set(key, group);
  }
  return [...groups.values()].sort((a, b) => a.time - b.time).map((group) => {
    const money = `${group.pnl >= 0 ? "+" : "-"}$${Math.abs(group.pnl).toFixed(2)}`;
    const many = group.count > 1 ? `${group.count}× ` : "";
    if (group.kind === "long") return { time: group.time, position: "belowBar", shape: "arrowUp", color: "#00ff8e", text: `${many}LONG`, kind: group.kind };
    if (group.kind === "short") return { time: group.time, position: "aboveBar", shape: "arrowDown", color: "#ff5780", text: `${many}SHORT`, kind: group.kind };
    const above = group.side === "LONG";
    if (group.kind === "tp") return { time: group.time, position: above ? "aboveBar" : "belowBar", shape: above ? "arrowDown" : "arrowUp", color: "#ffc320", text: `TP ${money}`, kind: group.kind };
    return { time: group.time, position: above ? "aboveBar" : "belowBar", shape: "circle", color: "#c9c3b0", text: `UIT ${group.side} ${money}`, kind: group.kind };
  });
}
