const HOUR = 60 * 60 * 1000;
const DAY = 24 * HOUR;

export const TRADE_NEWS_TIMEFRAMES = [
  { key: "15m", label: "15 min" },
  { key: "1h", label: "1 uur" },
  { key: "4h", label: "4 uur" },
  { key: "today", label: "Vandaag" },
  { key: "24h", label: "24 uur" },
  { key: "cycle", label: "Cyclus" },
];

export const TRADE_NEWS_FILTERS = [
  { key: "all", label: "Alles" },
  { key: "wins", label: "Winnaars" },
  { key: "pressure", label: "Onder druk" },
  { key: "updates", label: "Updates" },
  { key: "portfolio", label: "Portfolio" },
];

export function finiteNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function timestampMs(value) {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return value < 10_000_000_000 ? value * 1000 : value;
  }
  if (typeof value === "string" && value.trim()) {
    const numeric = Number(value);
    if (Number.isFinite(numeric) && numeric > 0) return numeric < 10_000_000_000 ? numeric * 1000 : numeric;
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  if (value && typeof value === "object") {
    const seconds = finiteNumber(value.seconds);
    const nanos = finiteNumber(value.nanoseconds) || 0;
    return seconds && seconds > 0 ? seconds * 1000 + Math.floor(nanos / 1_000_000) : 0;
  }
  return 0;
}

export function normalizeSymbol(value = "") {
  return String(value).toUpperCase().replace(/[^A-Z0-9]/g, "");
}

export function baseAsset(value = "") {
  return normalizeSymbol(value).replace(/(USDT|USDC|USD|PERP)$/i, "").replace(/^1000(?=[A-Z])/, "") || "?";
}

export function timeframeStart(timeframe, now = Date.now()) {
  if (timeframe === "15m") return now - 15 * 60 * 1000;
  if (timeframe === "1h") return now - HOUR;
  if (timeframe === "4h") return now - 4 * HOUR;
  if (timeframe === "24h") return now - DAY;
  if (timeframe === "today") {
    const date = new Date(now);
    date.setHours(0, 0, 0, 0);
    return date.getTime();
  }
  return 0;
}

export function timeframeLabel(timeframe) {
  return TRADE_NEWS_TIMEFRAMES.find((item) => item.key === timeframe)?.label || "24 uur";
}

export function positionPriceMovePct(position) {
  const entry = finiteNumber(position?.averageEntry) ?? finiteNumber(position?.entryPrice);
  const mark = finiteNumber(position?.markPrice);
  if (entry === null || entry <= 0 || mark === null || mark <= 0) return null;
  const raw = ((mark - entry) / entry) * 100;
  return String(position?.side || position?.positionSide || "").toUpperCase() === "SHORT" ? -raw : raw;
}

export function liquidationDistancePct(position) {
  const side = String(position?.side || position?.positionSide || "").toUpperCase();
  const mark = finiteNumber(position?.markPrice);
  const liquidation = finiteNumber(position?.liquidationPrice);
  if (mark === null || mark <= 0 || liquidation === null || liquidation <= 0) return null;
  if (side === "LONG") return Math.max(0, ((mark - liquidation) / mark) * 100);
  if (side === "SHORT") return Math.max(0, ((liquidation - mark) / mark) * 100);
  return null;
}

function readArray(value, key) {
  return value && typeof value === "object" && Array.isArray(value[key]) ? value[key] : [];
}

export function accountPositions(account) {
  const direct = readArray(account, "positions");
  if (direct.length) return direct.filter((row) => row && typeof row === "object");
  for (const key of ["snapshot", "account", "data", "aster"]) {
    const nested = account && typeof account === "object" ? account[key] : null;
    const rows = readArray(nested, "positions");
    if (rows.length) return rows.filter((row) => row && typeof row === "object");
  }
  return [];
}

export function closedTrades(history) {
  return readArray(history, "closedTrades").filter((row) => row && typeof row === "object");
}

export function recentTradeActivity(history) {
  const value = history && typeof history === "object" ? history.recentTradeActivity : null;
  return {
    entries: readArray(value, "entries").filter((row) => row && typeof row === "object"),
    exits: readArray(value, "exits").filter((row) => row && typeof row === "object"),
  };
}

function normalizedSide(row) {
  return String(row?.side || row?.positionSide || "").toUpperCase();
}

function activityTime(row) {
  return timestampMs(row?.timestampMs || row?.executedAt || row?.closedAt);
}

function matchingActivity(row, symbol, side) {
  return normalizeSymbol(row?.symbol) === normalizeSymbol(symbol) && normalizedSide(row) === side;
}

function stableCloseId(row) {
  return String(row?.exchangeTradeId || row?.exchangeTransactionId || row?.id || `${normalizeSymbol(row?.symbol)}:${normalizedSide(row)}:${timestampMs(row?.closedAt)}`);
}

export function activityEventsForItem(item, history) {
  if (!item?.symbol || !item?.side) return [];
  const activity = recentTradeActivity(history);
  const symbol = normalizeSymbol(item.symbol);
  const side = String(item.side).toUpperCase();
  let start = timestampMs(item.openedAt);
  const end = timestampMs(item.closedAt) || Date.now();

  if (!start) {
    const closes = activity.exits
      .filter((row) => matchingActivity(row, symbol, side) && activityTime(row) < end - 1000)
      .sort((a, b) => activityTime(b) - activityTime(a));
    start = closes.length ? activityTime(closes[0]) + 1000 : 0;
  }

  const entries = activity.entries
    .filter((row) => matchingActivity(row, symbol, side))
    .filter((row) => {
      const at = activityTime(row);
      return at > 0 && at >= start && at <= end + 2000;
    })
    .sort((a, b) => activityTime(a) - activityTime(b));

  const events = entries.map((row, index) => ({
    id: String(row.id || row.exchangeTradeId || `${symbol}:${side}:entry:${activityTime(row)}`),
    kind: index === 0 ? "entry" : "dca",
    dcaNumber: index === 0 ? null : index,
    symbol,
    side,
    price: finiteNumber(row.averagePrice) ?? finiteNumber(row.price),
    quantity: finiteNumber(row.quantity),
    notionalUsd: finiteNumber(row.executedNotionalUsd),
    at: row.executedAt || new Date(activityTime(row)).toISOString(),
    timestampMs: activityTime(row),
  })).filter((event) => event.price !== null && event.timestampMs > 0);

  if (item.closedAt && finiteNumber(item.exitPrice) !== null) {
    const closedAt = timestampMs(item.closedAt);
    events.push({
      id: `${item.id}:close`,
      kind: "close",
      dcaNumber: null,
      symbol,
      side,
      price: finiteNumber(item.exitPrice),
      quantity: null,
      notionalUsd: finiteNumber(item.notionalUsd),
      at: item.closedAt,
      timestampMs: closedAt,
    });
  }
  return events.sort((a, b) => a.timestampMs - b.timestampMs);
}

export function weightedAverageEntry(events) {
  const increases = (Array.isArray(events) ? events : []).filter((event) => event && (event.kind === "entry" || event.kind === "dca"));
  let quantity = 0;
  let notional = 0;
  for (const event of increases) {
    const qty = finiteNumber(event.quantity);
    const price = finiteNumber(event.price);
    const executed = finiteNumber(event.notionalUsd);
    if (qty !== null && qty > 0 && price !== null && price > 0) {
      quantity += qty;
      notional += executed !== null && executed > 0 ? executed : qty * price;
    }
  }
  return quantity > 0 ? notional / quantity : null;
}

function winItem(trade) {
  const symbol = normalizeSymbol(trade.symbol);
  const side = normalizedSide(trade);
  const pnl = finiteNumber(trade.realizedPnlUsd) ?? 0;
  const closedAt = timestampMs(trade.closedAt);
  const openedAt = timestampMs(trade.openedAt);
  const durationMs = openedAt && closedAt > openedAt ? closedAt - openedAt : null;
  const roi = finiteNumber(trade.returnPct) ?? finiteNumber(trade.roiPct) ?? finiteNumber(trade.roePct);
  return {
    id: `winner:${stableCloseId(trade)}`,
    type: "winner",
    tone: "profit",
    filter: "wins",
    priority: 500,
    occurredAt: closedAt,
    eyebrow: "WINST GESLOTEN",
    symbol,
    side,
    title: `${baseAsset(symbol)} sluit succesvolle cyclus`,
    pnlUsd: pnl,
    roiPct: roi,
    leverage: finiteNumber(trade.leverage),
    dcaCount: finiteNumber(trade.dcaCount),
    entryPrice: finiteNumber(trade.entryPrice),
    averageEntry: finiteNumber(trade.averageEntry) ?? finiteNumber(trade.entryPrice),
    currentPrice: null,
    exitPrice: finiteNumber(trade.exitPrice),
    breakEvenPrice: finiteNumber(trade.breakEvenPrice),
    liquidationDistancePct: null,
    feesUsd: finiteNumber(trade.commissionUsd) ?? finiteNumber(trade.feesUsd),
    durationMs,
    openedAt: trade.openedAt || null,
    closedAt: trade.closedAt || null,
    notionalUsd: finiteNumber(trade.notionalUsd),
    position: null,
    source: trade,
  };
}

function pressureItem(position, now) {
  const symbol = normalizeSymbol(position.symbol);
  const side = normalizedSide(position);
  const pnl = finiteNumber(position.unrealizedPnl) ?? finiteNumber(position.unRealizedProfit) ?? 0;
  const move = positionPriceMovePct(position);
  const dcaCount = finiteNumber(position.dcaCount) ?? finiteNumber(position?.strategy2DcaLadder?.filledDcaCount);
  const averageEntry = finiteNumber(position.averageEntry) ?? finiteNumber(position.entryPrice);
  const breakEven = finiteNumber(position?.strategy2Tp?.breakEvenPrice) ?? averageEntry;
  return {
    id: `pressure:${symbol}:${side}`,
    type: "pressure",
    tone: "loss",
    filter: "pressure",
    priority: 430 + Math.min(50, Math.abs(move || 0) * 4),
    occurredAt: now,
    eyebrow: "ONDER DRUK",
    symbol,
    side,
    title: `${baseAsset(symbol)} onder druk`,
    pnlUsd: pnl,
    roiPct: move,
    leverage: finiteNumber(position.leverage),
    dcaCount,
    entryPrice: finiteNumber(position.entryPrice),
    averageEntry,
    currentPrice: finiteNumber(position.markPrice),
    exitPrice: null,
    breakEvenPrice: breakEven,
    liquidationDistancePct: liquidationDistancePct(position),
    feesUsd: null,
    durationMs: null,
    openedAt: position.openedAt || null,
    closedAt: null,
    notionalUsd: finiteNumber(position.notionalUsd),
    position,
    source: position,
  };
}

function portfolioItem(closes, timeframe, now) {
  if (!closes.length) return null;
  const profitable = closes.filter((trade) => (finiteNumber(trade.realizedPnlUsd) ?? 0) > 0);
  const pnl = profitable.reduce((sum, trade) => sum + (finiteNumber(trade.realizedPnlUsd) ?? 0), 0);
  const totalPnl = closes.reduce((sum, trade) => sum + (finiteNumber(trade.realizedPnlUsd) ?? 0), 0);
  const ratio = closes.length ? profitable.length / closes.length * 100 : null;
  return {
    id: `portfolio:${timeframe}:${Math.floor(now / 60_000)}`,
    type: "portfolio",
    tone: "portfolio",
    filter: "portfolio",
    priority: 210,
    occurredAt: now,
    eyebrow: "PORTFOLIO UPDATE",
    symbol: "",
    side: "",
    title: `${profitable.length} winstgevende trade${profitable.length === 1 ? "" : "s"} gesloten`,
    pnlUsd: pnl,
    totalPnlUsd: totalPnl,
    roiPct: null,
    leverage: null,
    dcaCount: null,
    entryPrice: null,
    averageEntry: null,
    currentPrice: null,
    exitPrice: null,
    breakEvenPrice: null,
    liquidationDistancePct: null,
    feesUsd: null,
    durationMs: null,
    openedAt: null,
    closedAt: null,
    notionalUsd: null,
    position: null,
    source: { profitableCount: profitable.length, closedCount: closes.length, winRate: ratio, totalPnlUsd: totalPnl, timeframe },
  };
}

export function buildTradeNews({ account = {}, history = {}, timeframe = "24h", now = Date.now() } = {}) {
  const start = timeframeStart(timeframe, now);
  const closes = closedTrades(history)
    .filter((trade) => {
      const at = timestampMs(trade.closedAt);
      return at > 0 && (start === 0 || at >= start) && at <= now + 60_000;
    })
    .sort((a, b) => timestampMs(b.closedAt) - timestampMs(a.closedAt));

  const winners = closes
    .filter((trade) => (finiteNumber(trade.realizedPnlUsd) ?? 0) > 0)
    .map(winItem);

  const pressure = accountPositions(account)
    .filter((position) => {
      const quantity = finiteNumber(position.quantity) ?? finiteNumber(position.positionAmt) ?? 0;
      const pnl = finiteNumber(position.unrealizedPnl) ?? finiteNumber(position.unRealizedProfit) ?? 0;
      const move = positionPriceMovePct(position);
      return quantity > 0 && pnl < 0 && move !== null && move <= -0.35;
    })
    .map((position) => pressureItem(position, now));

  const portfolio = portfolioItem(closes, timeframe, now);
  const items = [...winners, ...pressure, ...(portfolio ? [portfolio] : [])];
  const unique = new Map();
  for (const item of items) {
    const current = unique.get(item.id);
    if (!current || item.priority > current.priority || item.occurredAt > current.occurredAt) unique.set(item.id, item);
  }
  return Array.from(unique.values()).sort((a, b) => (b.priority - a.priority) || (b.occurredAt - a.occurredAt));
}

export function recoveryFromCandles(position, candles, timeframe = "24h", now = Date.now()) {
  if (!position || !Array.isArray(candles) || candles.length < 2) return null;
  const symbol = normalizeSymbol(position.symbol);
  const side = normalizedSide(position);
  const mark = finiteNumber(position.markPrice);
  if (!symbol || !["LONG", "SHORT"].includes(side) || mark === null || mark <= 0) return null;
  const start = timeframeStart(timeframe, now);
  const rows = candles.filter((row) => {
    const at = (finiteNumber(row.time) ?? 0) * 1000;
    return at > 0 && (start === 0 || at >= start) && at <= now + 60_000;
  });
  if (rows.length < 2) return null;
  const values = side === "LONG"
    ? rows.map((row) => finiteNumber(row.low)).filter((value) => value !== null)
    : rows.map((row) => finiteNumber(row.high)).filter((value) => value !== null);
  if (!values.length) return null;
  const adverse = side === "LONG" ? Math.min(...values) : Math.max(...values);
  if (!Number.isFinite(adverse) || adverse <= 0) return null;
  const recoveryPct = side === "LONG"
    ? ((mark - adverse) / adverse) * 100
    : ((adverse - mark) / adverse) * 100;
  if (!Number.isFinite(recoveryPct) || recoveryPct < 0.60) return null;
  const pnl = finiteNumber(position.unrealizedPnl) ?? finiteNumber(position.unRealizedProfit) ?? 0;
  if (pnl >= 0) return null;
  const averageEntry = finiteNumber(position.averageEntry) ?? finiteNumber(position.entryPrice);
  return {
    id: `recovery:${symbol}:${side}`,
    type: "recovery",
    tone: "recovery",
    filter: "updates",
    priority: 350 + Math.min(40, recoveryPct * 3),
    occurredAt: now,
    eyebrow: "HERSTEL UPDATE",
    symbol,
    side,
    title: `${baseAsset(symbol)} herstelt ${recoveryPct.toFixed(1).replace(".", ",")}% vanaf dieptepunt`,
    pnlUsd: pnl,
    roiPct: recoveryPct,
    leverage: finiteNumber(position.leverage),
    dcaCount: finiteNumber(position.dcaCount) ?? finiteNumber(position?.strategy2DcaLadder?.filledDcaCount),
    entryPrice: finiteNumber(position.entryPrice),
    averageEntry,
    currentPrice: mark,
    exitPrice: null,
    breakEvenPrice: finiteNumber(position?.strategy2Tp?.breakEvenPrice) ?? averageEntry,
    liquidationDistancePct: liquidationDistancePct(position),
    feesUsd: null,
    durationMs: null,
    openedAt: position.openedAt || null,
    closedAt: null,
    notionalUsd: finiteNumber(position.notionalUsd),
    position,
    source: { adversePrice: adverse, recoveryPct, timeframe },
  };
}

export function dcaUpdateFromEvents(item, events, timeframe = "24h", now = Date.now()) {
  if (!item?.symbol || !Array.isArray(events)) return null;
  const start = timeframeStart(timeframe, now);
  const dcas = events.filter((event) => event?.kind === "dca" && timestampMs(event.timestampMs || event.at) >= start);
  if (!dcas.length) return null;
  const latest = dcas[dcas.length - 1];
  return {
    id: `dca:${normalizeSymbol(item.symbol)}:${item.side}:${latest.id || timestampMs(latest.at)}`,
    type: "update",
    tone: "recovery",
    filter: "updates",
    priority: 320,
    occurredAt: timestampMs(latest.timestampMs || latest.at) || now,
    eyebrow: "DCA UPDATE",
    symbol: item.symbol,
    side: item.side,
    title: `${baseAsset(item.symbol)} · DCA ${dcas.length} uitgevoerd`,
    pnlUsd: item.pnlUsd,
    roiPct: item.roiPct,
    leverage: item.leverage,
    dcaCount: item.dcaCount ?? dcas.length,
    entryPrice: item.entryPrice,
    averageEntry: weightedAverageEntry(events) ?? item.averageEntry,
    currentPrice: item.currentPrice,
    exitPrice: item.exitPrice,
    breakEvenPrice: item.breakEvenPrice,
    liquidationDistancePct: item.liquidationDistancePct,
    feesUsd: item.feesUsd,
    durationMs: item.durationMs,
    openedAt: item.openedAt,
    closedAt: item.closedAt,
    notionalUsd: item.notionalUsd,
    position: item.position,
    source: { latestDca: latest, dcaCount: dcas.length },
  };
}

export function candleConfigForTimeframe(timeframe) {
  if (timeframe === "15m") return { interval: "1m", limit: 100 };
  if (timeframe === "1h") return { interval: "1m", limit: 120 };
  if (timeframe === "4h") return { interval: "5m", limit: 100 };
  if (timeframe === "today") return { interval: "15m", limit: 100 };
  if (timeframe === "cycle") return { interval: "5m", limit: 240 };
  return { interval: "15m", limit: 100 };
}

export function filterTradeNews(items, filter) {
  if (filter === "all") return items;
  return items.filter((item) => item.filter === filter);
}
