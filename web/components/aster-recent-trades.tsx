"use client";

import { useMemo, useRef, useState, type TouchEvent } from "react";
import { createPortal } from "react-dom";
import type { ExchangeSnapshot } from "@/lib/use-exchange-data";
import { authenticatedRequest } from "@/lib/cloud-client";
import { activityTime, reliableReturnPct, sortedActivity, stableActivityId } from "@/lib/recent-trades.mjs";
import { authoritativePositionReturnPct, positionId, topProfitPositions } from "@/lib/top-profit-positions.mjs";
import { SafeTradingChart, type AirbagChartEvent, type DcaChartLevel, type TradeSelection } from "@/components/trading-chart";
import styles from "./aster-trade-center.module.css";

type Activity = {
  id?: string; exchangeTradeId?: string; symbol?: string; side?: string; quantity?: number;
  executedNotionalUsd?: number | null; costBasisUsd?: number | null; realizedPnlUsd?: number;
  unrealizedPnlUsd?: number | null; returnPct?: number | null; roePct?: number | null; roiPct?: number | null;
  leverage?: number | null; marginUsd?: number | null; initialMarginUsd?: number | null;
  timestampMs?: number; executedAt?: string; closedAt?: string;
};

type OpenPosition = {
  id?: string; positionId?: string; symbol?: string; side?: string; quantity?: number; notionalUsd?: number | null;
  markPrice?: number | null; unrealizedPnl?: number | null; returnPct?: number | null; roePct?: number | null;
  roiPct?: number | null; leverage?: number | null; initialMarginUsd?: number | null; dcaCount?: number | null;
  openedAt?: unknown; entryPrice?: number | null; averageEntry?: number | null;
  strategy2Tp?: { breakEvenPrice?: number | null; ownershipProven?: boolean; status?: string } | null;
  strategy2DcaLadder?: { available?: boolean; mode?: string; filledDcaCount?: number; maxDca?: number; levels?: DcaChartLevel[] } | null;
  focusAirbag?: { enabled?: boolean; status?: string; mainSide?: string; mainNotional?: number; hedgeSide?: string; hedgeNotional?: number; hedgeRatio?: number; targetRatio?: number; hedgePnl?: number; mainPnl?: number; combinedPnl?: number; reason?: string; nextAction?: string; nextActionPrice?: number | null; lastUpdatedAt?: number; events?: AirbagChartEvent[] } | null;
  focusAirbagHedge?: boolean;
};

type ScanAction = {
  clientOrderId?: string; symbol?: string; side?: string; action?: string; kind?: string; leverage?: number | null;
  marginUsd?: number | null; dcaNumber?: number | null; executedAt?: unknown; orderId?: string;
};

type FilterKey = "live" | "entered" | "closed" | "tp" | "dca" | "profit" | "loss" | "actions";
type AsterPairDetail = {
  selection: TradeSelection; focusAtMs?: number; averageEntry?: number | null; selectedActionId?: string;
  status?: "OPEN" | "CLOSED"; pnl?: number | null; quantity?: number | null; dcaCount?: number | null;
  currentPrice?: number | null; exitPrice?: number | null;
};

type TradeCenterRow = {
  id: string; symbol: string; side: string; leverage: number | null; margin: number | null; pnl: number | null;
  status: string; timestamp?: unknown; tone: "profit" | "loss" | "neutral"; source: "position" | "activity" | "action";
  position?: OpenPosition | null; activity?: Activity | null; action?: ScanAction | null;
};

const suffixes = ["USDT", "USDC", "USD"];
const TP_KINDS = new Set(["FULL_TP", "PARTIAL_TP", "TAKE_PROFIT_CLOSE"]);
const DCA_KINDS = new Set(["ADD_DCA", "PROTECTION_INCREASE"]);
const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "live", label: "Live" }, { key: "entered", label: "Ingestapt" }, { key: "closed", label: "Gesloten" },
  { key: "tp", label: "TP" }, { key: "dca", label: "DCA" }, { key: "profit", label: "Hoogste winst" },
  { key: "loss", label: "Hoogste verlies" }, { key: "actions", label: "Botacties" },
];

function finite(value: unknown) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value); return Number.isFinite(n) ? n : null;
}
function normalizedSymbol(symbol = "") { return symbol.toUpperCase().replace(/[\/_-]/g, ""); }
function baseAsset(symbol = "") {
  const value = normalizedSymbol(symbol);
  return suffixes.reduce((v, suffix) => v.endsWith(suffix) ? v.slice(0, -suffix.length) : v, value) || "?";
}
function amount(value: unknown, signed = false) {
  const n = finite(value); if (n === null) return "—";
  return `${signed && n > 0 ? "+" : ""}${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: Math.abs(n) < .01 && n !== 0 ? 4 : 2 }).format(n)}`;
}
function money(value: unknown, signed = false) { const n = finite(value); return n === null ? "—" : `$${amount(n, signed)}`; }
function exchangeTimestampMs(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) return value < 10_000_000_000 ? value * 1000 : value;
  if (typeof value === "string" && value.trim()) { const n = Number(value); if (Number.isFinite(n) && n > 0) return n < 10_000_000_000 ? n * 1000 : n; const parsed = Date.parse(value); return Number.isFinite(parsed) ? parsed : 0; }
  if (value && typeof value === "object") { const row = value as Record<string, unknown>; const seconds = finite(row.seconds); const nanos = finite(row.nanoseconds) || 0; if (seconds !== null && seconds > 0) return seconds * 1000 + Math.floor(nanos / 1_000_000); }
  return 0;
}
function dateTime(value: unknown) {
  const timestamp = exchangeTimestampMs(value); if (!timestamp) return "—";
  const date = new Date(timestamp); const day = new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "short" }).format(date);
  const clock = new Intl.DateTimeFormat("nl-NL", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date);
  return `${day} · ${clock}`;
}
function sideKey(row: { symbol?: string; side?: string }) { return `${normalizedSymbol(row.symbol)}|${String(row.side || "").toUpperCase()}`; }
function findOpenPosition(positions: OpenPosition[], row: { symbol?: string; side?: string }) {
  const key = sideKey(row); return positions.find(position => sideKey(position) === key && (finite(position.quantity) || 0) > 0) || null;
}
function averageEntry(position: OpenPosition | null) { return finite(position?.averageEntry) ?? finite(position?.entryPrice); }
function openPositionMargin(position: OpenPosition | null) {
  if (!position) return null; const direct = finite(position.initialMarginUsd); if (direct !== null && direct > 0) return direct;
  const notional = finite(position.notionalUsd); const leverage = finite(position.leverage);
  if (notional !== null && notional > 0 && leverage !== null && leverage > 0) return notional / leverage;
  return direct === 0 && notional === 0 ? 0 : null;
}
function activityLeverage(trade: Activity, position: OpenPosition | null) {
  const direct = finite(trade.leverage); if (direct !== null && direct >= 1) return Math.round(direct);
  const live = finite(position?.leverage); return live !== null && live >= 1 ? Math.round(live) : null;
}
function activityMargin(trade: Activity, position: OpenPosition | null, leverage: number | null) {
  for (const value of [trade.marginUsd, trade.initialMarginUsd]) { const direct = finite(value); if (direct !== null && direct > 0) return direct; }
  const live = openPositionMargin(position); if (live !== null) return live;
  if (leverage && leverage > 0) { const basis = finite(trade.costBasisUsd) ?? finite(trade.executedNotionalUsd); if (basis !== null && basis > 0) return basis / leverage; }
  return null;
}
function scanActionLabel(action: ScanAction) {
  const kind = String(action.kind || "").toUpperCase(); const orderAction = String(action.action || "").toUpperCase();
  if (kind === "FOCUS_AIRBAG_INCREASE") return "HEDGE +";
  if (kind === "FOCUS_AIRBAG_REDUCE") return "HEDGE -";
  if (orderAction === "CLOSE" || TP_KINDS.has(kind) || kind === "RISK_REDUCE") return TP_KINDS.has(kind) ? "TP" : "Gesloten";
  if (DCA_KINDS.has(kind)) return "DCA"; return "Instap";
}
function toneFor(value: unknown): "profit" | "loss" | "neutral" { const n = finite(value); return n === null || n === 0 ? "neutral" : n > 0 ? "profit" : "loss"; }

function CoinIcon({ symbol }: { symbol: string }) {
  const asset = baseAsset(symbol);
  return <span className={styles.coin}><img src={`https://assets.coincap.io/assets/icons/${asset.toLowerCase()}@2x.png`} alt="" loading="lazy" onError={event => { event.currentTarget.hidden = true; }} /><i>{asset.slice(0, 2)}</i></span>;
}

function ClosePositionControl({ position, onClosed }: { position: OpenPosition | null; onClosed: () => void }) {
  const [confirming, setConfirming] = useState(false); const [busy, setBusy] = useState(false); const [message, setMessage] = useState(""); const requestKey = useRef("");
  const tone = toneFor(position?.unrealizedPnl);
  async function closePosition() {
    if (busy || !position?.symbol || !position.side || !(finite(position.quantity) && Number(position.quantity) > 0)) return;
    setBusy(true); setMessage(""); if (!requestKey.current) requestKey.current = crypto.randomUUID();
    try {
      await authenticatedRequest(`/api/exchanges/aster/positions/${encodeURIComponent(String(position.symbol))}/close`, { method: "POST", body: JSON.stringify({ confirm: true, side: String(position.side).toUpperCase(), expected_quantity: Number(position.quantity), idempotency_key: requestKey.current }) });
      setConfirming(false); await onClosed();
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Sluiten is niet gelukt."); } finally { setBusy(false); }
  }
  return <><button type="button" className={`${styles.close} ${styles[tone]}`} disabled={busy || !position} onClick={() => position && setConfirming(true)}>{busy ? "…" : "Close"}</button>{confirming && position && typeof document !== "undefined" && createPortal(<div className={styles.modal} role="dialog" aria-modal="true"><div><h3>Positie market sluiten</h3><dl><dt>Coin</dt><dd>{baseAsset(position.symbol)}</dd><dt>Richting</dt><dd>{String(position.side).toUpperCase()}</dd><dt>Actuele grootte</dt><dd>{amount(position.quantity)}</dd><dt>Geschatte P&amp;L</dt><dd className={styles[tone]}>{money(position.unrealizedPnl, true)}</dd></dl><p>De volledige resterende positie wordt tegen marktprijs gesloten.</p><strong>Weet je zeker dat je deze volledige positie market wilt sluiten?</strong><footer><button type="button" disabled={busy} onClick={() => setConfirming(false)}>Annuleren</button><button type="button" disabled={busy} onClick={closePosition}>Volledig market sluiten</button></footer>{message && <small>{message}</small>}</div></div>, document.body)}</>;
}

function rowFromPosition(position: OpenPosition, status = "Live"): TradeCenterRow {
  const pnl = finite(position.unrealizedPnl); return { id: positionId(position), symbol: normalizedSymbol(position.symbol), side: String(position.side || "—").toUpperCase(), leverage: finite(position.leverage), margin: openPositionMargin(position), pnl, status, timestamp: position.openedAt, tone: toneFor(pnl), source: "position", position };
}
function rowFromActivity(trade: Activity, closed: boolean, positions: OpenPosition[], scanActions: ScanAction[]): TradeCenterRow {
  const position = closed ? null : findOpenPosition(positions, trade); const matching = closed ? [...scanActions].reverse().find(action => sideKey(action) === sideKey(trade) && String(action.action || "").toUpperCase() === "CLOSE") || null : null;
  const leverage = activityLeverage(trade, position) ?? finite(matching?.leverage); const margin = activityMargin(trade, position, leverage) ?? finite(matching?.marginUsd); const pnl = finite(closed ? trade.realizedPnlUsd : trade.unrealizedPnlUsd);
  return { id: String(trade.exchangeTradeId || trade.id || stableActivityId(trade)), symbol: normalizedSymbol(trade.symbol), side: String(trade.side || "—").toUpperCase(), leverage, margin, pnl, status: closed ? (matching && TP_KINDS.has(String(matching.kind || "").toUpperCase()) ? "TP" : "Gesloten") : "Ingestapt", timestamp: closed ? (trade.closedAt || trade.executedAt || trade.timestampMs) : (trade.executedAt || trade.timestampMs), tone: toneFor(pnl), source: "activity", activity: trade, position };
}
function rowFromAction(action: ScanAction, positions: OpenPosition[], exits: Activity[]): TradeCenterRow {
  const position = findOpenPosition(positions, action); const label = scanActionLabel(action); const exit = label === "TP" || label === "Gesloten" ? exits.find(row => sideKey(row) === sideKey(action)) : null; const pnl = position ? finite(position.unrealizedPnl) : finite(exit?.realizedPnlUsd);
  return { id: String(action.clientOrderId || action.orderId || `${normalizedSymbol(action.symbol)}:${exchangeTimestampMs(action.executedAt)}`), symbol: normalizedSymbol(action.symbol), side: String(action.side || "—").toUpperCase(), leverage: finite(action.leverage) ?? finite(position?.leverage), margin: finite(action.marginUsd) ?? openPositionMargin(position), pnl, status: label, timestamp: action.executedAt, tone: toneFor(pnl), source: "action", action, position };
}

function TradeCenterTable({ rows, onOpenDetail, onClosed }: { rows: TradeCenterRow[]; onOpenDetail: (row: TradeCenterRow) => void; onClosed: () => void }) {
  return <div className={styles.table} role="table" aria-label="Aster Tradecentrum"><div className={styles.head} role="row"><span>PAIR</span><span>SIDE</span><span>LEV</span><span>MARGIN</span><span>PNL</span><span>STATUS</span></div>{rows.length ? rows.map(row => <div className={styles.row} role="row" key={row.id}><button className={styles.pair} role="cell" type="button" onClick={() => onOpenDetail(row)}><CoinIcon symbol={row.symbol} /><span className={styles.pairCopy}><b>{baseAsset(row.symbol)}</b><small>{dateTime(row.timestamp)}</small></span></button><strong role="cell" className={`${styles.side} ${row.side === "LONG" ? styles.long : row.side === "SHORT" ? styles.short : styles.neutral}`}>{row.side}</strong><span role="cell">{row.leverage === null ? "—" : `${Math.round(row.leverage)}x`}</span><span role="cell">{money(row.margin)}</span><strong role="cell" className={styles[row.tone]}>{money(row.pnl, true)}</strong><span role="cell" className={styles.status}><span className={styles.statusText}>{row.status}</span>{row.source === "position" && row.position ? <ClosePositionControl position={row.position} onClosed={onClosed} /> : null}</span></div>) : <div className={styles.empty}>Geen bevestigde gegevens voor dit filter.</div>}</div>;
}

export function AsterRecentTrades({ snapshot, onRetry }: { snapshot: ExchangeSnapshot; onRetry: () => void }) {
  const [active, setActive] = useState<FilterKey>("live"); const [expanded, setExpanded] = useState(false); const [pages, setPages] = useState(1); const [detail, setDetail] = useState<AsterPairDetail | null>(null);
  const scrollYRef = useRef(0); const lastTapRef = useRef(0); const touchGestureRef = useRef({ valid: false, x: 0, y: 0 });
  const activity = snapshot.data?.recentTradeActivity && typeof snapshot.data.recentTradeActivity === "object" ? snapshot.data.recentTradeActivity as Record<string, unknown> : {};
  const entries = useMemo(() => sortedActivity(Array.isArray(activity.entries) ? activity.entries : []) as Activity[], [activity.entries]);
  const exits = useMemo(() => sortedActivity(Array.isArray(activity.exits) ? activity.exits : []) as Activity[], [activity.exits]);
  const allPositions = useMemo(() => (Array.isArray(snapshot.data?.positions) ? snapshot.data.positions : []) as OpenPosition[], [snapshot.data?.positions]);
  const displayPositions = useMemo(() => allPositions.filter(position => position.focusAirbagHedge !== true), [allPositions]);
  const strategy2 = snapshot.data?.strategy2 && typeof snapshot.data.strategy2 === "object" ? snapshot.data.strategy2 as Record<string, unknown> : {};
  const orderQueue = strategy2.orderQueue && typeof strategy2.orderQueue === "object" ? strategy2.orderQueue as Record<string, unknown> : {};
  const scanActions = useMemo(() => (Array.isArray(orderQueue.lastScanActions) ? orderQueue.lastScanActions : []) as ScanAction[], [orderQueue.lastScanActions]);
  const reversedActions = useMemo(() => [...scanActions].reverse(), [scanActions]);
  const tpActions = useMemo(() => reversedActions.filter(action => TP_KINDS.has(String(action.kind || "").toUpperCase())), [reversedActions]);
  const dcaActions = useMemo(() => reversedActions.filter(action => DCA_KINDS.has(String(action.kind || "").toUpperCase())), [reversedActions]);
  const profitPositions = useMemo(() => topProfitPositions(displayPositions) as OpenPosition[], [displayPositions]);
  const lossPositions = useMemo(() => [...displayPositions].filter(position => finite(position.quantity) && Number(position.quantity) > 0).sort((a, b) => (finite(a.unrealizedPnl) ?? 0) - (finite(b.unrealizedPnl) ?? 0)), [displayPositions]);
  const livePositions = useMemo(() => [...displayPositions].filter(position => finite(position.quantity) && Number(position.quantity) > 0).sort((a, b) => exchangeTimestampMs(b.openedAt) - exchangeTimestampMs(a.openedAt)), [displayPositions]);
  const datasets = useMemo<Record<FilterKey, TradeCenterRow[]>>(() => ({
    live: livePositions.map(position => rowFromPosition(position)), entered: entries.map(trade => rowFromActivity(trade, false, allPositions, scanActions)), closed: exits.map(trade => rowFromActivity(trade, true, allPositions, scanActions)),
    tp: tpActions.map(action => rowFromAction(action, allPositions, exits)), dca: dcaActions.map(action => rowFromAction(action, allPositions, exits)), profit: profitPositions.map(position => rowFromPosition(position, "Live")), loss: lossPositions.map(position => rowFromPosition(position, "Live")), actions: reversedActions.map(action => rowFromAction(action, allPositions, exits)),
  }), [livePositions, entries, exits, allPositions, scanActions, tpActions, dcaActions, profitPositions, lossPositions, reversedActions]);
  const counts: Record<FilterKey, number> = { live: livePositions.length, entered: entries.length, closed: exits.length, tp: tpActions.length, dca: dcaActions.length, profit: profitPositions.length, loss: lossPositions.length, actions: scanActions.length };
  const selectedRows = datasets[active]; const visibleLimit = expanded ? pages * 100 : 6; const visibleRows = selectedRows.slice(0, visibleLimit); const hasMore = visibleRows.length < selectedRows.length;
  const liveState = snapshot.error ? "Offline" : snapshot.loading ? "Reconnecting" : snapshot.updatedAt && Date.now() - snapshot.updatedAt < 90_000 ? "Live" : "Delayed";
  const liveDetailPosition = detail?.status === "OPEN" ? findOpenPosition(allPositions, detail.selection) : null;
  const detailAverageEntry = averageEntry(liveDetailPosition) ?? detail?.averageEntry ?? null;
  const detailCurrentPrice = finite(liveDetailPosition?.markPrice) ?? detail?.currentPrice ?? null;
  const detailPnl = finite(liveDetailPosition?.unrealizedPnl) ?? detail?.pnl ?? null;
  const detailQuantity = finite(liveDetailPosition?.quantity) ?? detail?.quantity ?? null;
  const detailDcaCount = finite(liveDetailPosition?.dcaCount) ?? detail?.dcaCount ?? null;
  const detailBreakEvenPrice = finite(liveDetailPosition?.strategy2Tp?.breakEvenPrice) ?? undefined;
  const detailDcaLevels = useMemo(() => {
    const levels = liveDetailPosition?.strategy2DcaLadder?.levels;
    if (!Array.isArray(levels)) return [] as DcaChartLevel[];
    return levels.filter(level => finite(level?.number) !== null && finite(level?.price) !== null && Number(level.price) > 0).map(level => ({ number:Number(level.number), price:Number(level.price) }));
  }, [liveDetailPosition?.strategy2DcaLadder?.levels]);
  const detailAirbag=liveDetailPosition?.focusAirbag || null;
  const detailAirbagEvents=Array.isArray(detailAirbag?.events)?detailAirbag.events.filter((event):event is AirbagChartEvent=>Boolean(event&&Number.isFinite(Number(event.at))&&Number.isFinite(Number(event.price)))):[];
  function selectFilter(key: FilterKey) { setActive(key); setExpanded(false); setPages(1); }
  function openDetail(row: TradeCenterRow) {
    scrollYRef.current = window.scrollY; const position = row.position || null; const trade = row.activity; const action = row.action;
    setDetail({ selection: { id: row.id, symbol: row.symbol, exchange: "aster", side: row.side, entry: averageEntry(position), mark: finite(position?.markPrice) ?? undefined, dcaCount: finite(position?.dcaCount) ?? undefined, openedAt: row.source === "position" && exchangeTimestampMs(row.timestamp) ? new Date(exchangeTimestampMs(row.timestamp)).toISOString() : undefined, closedAt: row.status === "Gesloten" || row.status === "TP" ? String(trade?.closedAt || trade?.executedAt || (exchangeTimestampMs(row.timestamp) ? new Date(exchangeTimestampMs(row.timestamp)).toISOString() : "")) : undefined }, focusAtMs: row.source === "activity" && (row.status === "Gesloten" || row.status === "TP") ? exchangeTimestampMs(row.timestamp) : row.source === "action" ? exchangeTimestampMs(action?.executedAt) : undefined, averageEntry: averageEntry(position), selectedActionId: action ? String(action.clientOrderId || action.orderId || "") : undefined, status: row.status === "Gesloten" || row.status === "TP" ? "CLOSED" : "OPEN", pnl: row.pnl, quantity: finite(trade?.quantity) ?? finite(position?.quantity), dcaCount: finite(position?.dcaCount) ?? finite(action?.dcaNumber), currentPrice: finite(position?.markPrice), exitPrice: row.status === "Gesloten" || row.status === "TP" ? null : undefined });
  }
  function closeDetail() { setDetail(null); requestAnimationFrame(() => window.scrollTo({ top: scrollYRef.current, behavior: "auto" })); }
  function handleTouchStart(event: TouchEvent<HTMLDivElement>) { if (event.touches.length !== 1) { touchGestureRef.current.valid = false; return; } const touch = event.touches[0]; touchGestureRef.current = { valid: true, x: touch.clientX, y: touch.clientY }; }
  function handleTouchMove(event: TouchEvent<HTMLDivElement>) { if (!touchGestureRef.current.valid || event.touches.length !== 1) return; const touch = event.touches[0]; if (Math.hypot(touch.clientX - touchGestureRef.current.x, touch.clientY - touchGestureRef.current.y) > 10) touchGestureRef.current.valid = false; }
  function handleTouchEnd(event: TouchEvent<HTMLDivElement>) { if (!touchGestureRef.current.valid || event.changedTouches.length !== 1) { lastTapRef.current = 0; return; } touchGestureRef.current.valid = false; const now = Date.now(); if (now - lastTapRef.current < 320) { lastTapRef.current = 0; closeDetail(); } else lastTapRef.current = now; }
  if (snapshot.error && !entries.length && !exits.length && !allPositions.length) return <section className={styles.error}><span>Tradegegevens tijdelijk niet beschikbaar</span><button type="button" onClick={onRetry}>Opnieuw proberen</button></section>;
  return <section className={`${styles.shell} ${styles.detailShell} ${detail ? styles.detailOpen : ""}`} aria-label="Aster Tradecentrum"><div className={styles.detailInner}><div className={styles.front} aria-hidden={Boolean(detail)} inert={detail ? true : undefined}><article className={styles.card}><header className={styles.header}><div className={styles.title}><h2>Tradecentrum</h2><p>Eén overzicht · acht live filters</p></div><span className={`${styles.live} ${styles[liveState.toLowerCase()] || ""}`}>{liveState}</span></header><nav className={styles.filters} aria-label="Tradecentrum filters">{FILTERS.map(filter => <button type="button" key={filter.key} className={`${styles.filter} ${active === filter.key ? styles.active : ""}`} aria-pressed={active === filter.key} onClick={() => selectFilter(filter.key)}>{filter.label}<b>{counts[filter.key]}</b></button>)}</nav><TradeCenterTable rows={visibleRows} onOpenDetail={openDetail} onClosed={onRetry} /><footer className={styles.footer}>{selectedRows.length > 6 && <button type="button" onClick={() => { setExpanded(value => !value); setPages(1); }}>{expanded ? "Compact tonen" : "Toon alles"}</button>}{expanded && hasMore && <button type="button" onClick={() => setPages(value => value + 1)}>Laad nog 100</button>}</footer></article></div><div className={styles.back} aria-hidden={!detail} inert={!detail ? true : undefined} onDoubleClick={closeDetail} onTouchStart={handleTouchStart} onTouchMove={handleTouchMove} onTouchEnd={handleTouchEnd}>{detail && <><header className={styles.detailHeader}><div><span>ASTER · TRADEDETAIL</span><h2>{baseAsset(detail.selection.symbol)} <i>/ USDT</i></h2><small>{String(detail.selection.side || "").toUpperCase()} · dubbel tikken om terug te gaan</small></div><button type="button" onClick={closeDetail} aria-label="Terug naar Tradecentrum">×</button></header><SafeTradingChart selection={detail.selection} mode="aster-detail" focusAtMs={detail.focusAtMs} breakEvenPrice={detailBreakEvenPrice} dcaLevels={detailDcaLevels} selectedActionId={detail.selectedActionId} airbagEvents={detailAirbagEvents} /><div className={styles.summary}><div><span>Positie</span><strong className={detail.status === "OPEN" ? styles.profit : styles.neutral}>{detail.status || "—"}</strong></div><div><span>Entry prijs (gem.)</span><strong>{money(detailAverageEntry)}</strong></div><div><span>{detail.status === "CLOSED" ? "Exit prijs" : "Huidige prijs"}</span><strong>{money(detail.status === "CLOSED" ? detail.exitPrice : detailCurrentPrice)}</strong></div><div><span>{detail.status === "CLOSED" ? "Realized P&L" : "Unrealized P&L"}</span><strong className={(detailPnl ?? 0) >= 0 ? styles.profit : styles.loss}>{money(detailPnl, true)}</strong></div><div><span>Aantal DCA</span><strong>{detailDcaCount === null || detailDcaCount === undefined ? "—" : Math.round(detailDcaCount)}</strong></div><div><span>Totale hoeveelheid</span><strong>{detailQuantity === null || detailQuantity === undefined ? "—" : amount(detailQuantity)}</strong></div></div>{detailAirbag&&<section className={styles.airbag} aria-label="Portfolio Airbag"><header><div><span>PORTFOLIO AIRBAG</span><strong>{String(detailAirbag.status||"WACHT")}</strong></div><b>{((finite(detailAirbag.hedgeRatio)||0)*100).toFixed(0)}%</b></header><div className={styles.airbagGrid}><div><span>Hoofdpositie</span><strong>{String(detailAirbag.mainSide||detail.selection.side)} · {money(detailAirbag.mainNotional)}</strong></div><div><span>Hedge</span><strong>{String(detailAirbag.hedgeSide||"—")} · {money(detailAirbag.hedgeNotional)}</strong></div><div><span>Hedge bijdrage</span><strong className={(finite(detailAirbag.hedgePnl)||0)>=0?styles.profit:styles.loss}>{money(detailAirbag.hedgePnl,true)}</strong></div><div><span>Gecombineerd P&L</span><strong className={(finite(detailAirbag.combinedPnl)||0)>=0?styles.profit:styles.loss}>{money(detailAirbag.combinedPnl,true)}</strong></div></div><p><b>Waarom:</b> {String(detailAirbag.reason||"Geen beschermingsactie nodig")}</p><p><b>Volgende actie:</b> {String(detailAirbag.nextAction||"Hedge stabiel")}</p>{detailAirbagEvents.length>0&&<div className={styles.airbagTimeline}>{detailAirbagEvents.slice(-10).reverse().map((event,index)=><div key={`${event.at}:${index}`}><time>{new Intl.DateTimeFormat("nl-NL",{hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(event.at))}</time><b>{event.kind}</b><span>{(Number(event.ratio)*100).toFixed(0)}%</span></div>)}</div>}</section>}</>}</div></div></section>;
}
