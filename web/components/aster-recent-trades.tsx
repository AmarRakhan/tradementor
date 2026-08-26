"use client";

import { memo, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { ExchangeSnapshot } from "@/lib/use-exchange-data";
import { authenticatedRequest } from "@/lib/cloud-client";
import { activityTime, pageActivity, reliableReturnPct, sortedActivity, stableActivityId } from "@/lib/recent-trades.mjs";
import { authoritativePositionReturnPct, positionId, topProfitPositions } from "@/lib/top-profit-positions.mjs";
import { SafeTradingChart, type TradeSelection } from "@/components/trading-chart";

type Activity = {
  id?: string;
  exchangeTradeId?: string;
  symbol?: string;
  side?: string;
  quantity?: number;
  executedNotionalUsd?: number | null;
  costBasisUsd?: number | null;
  realizedPnlUsd?: number;
  unrealizedPnlUsd?: number | null;
  returnPct?: number | null;
  roePct?: number | null;
  roiPct?: number | null;
  leverage?: number | null;
  marginUsd?: number | null;
  initialMarginUsd?: number | null;
  timestampMs?: number;
  executedAt?: string;
  closedAt?: string;
};

type OpenPosition = {
  id?: string;
  positionId?: string;
  symbol?: string;
  side?: string;
  quantity?: number;
  notionalUsd?: number | null;
  markPrice?: number | null;
  unrealizedPnl?: number | null;
  returnPct?: number | null;
  roePct?: number | null;
  roiPct?: number | null;
  leverage?: number | null;
  initialMarginUsd?: number | null;
  dcaCount?: number | null;
  openedAt?: unknown;
  entryPrice?: number | null;
  averageEntry?: number | null;
};

type ScanAction = {
  clientOrderId?: string;
  symbol?: string;
  side?: string;
  action?: string;
  kind?: string;
  leverage?: number | null;
  marginUsd?: number | null;
  dcaNumber?: number | null;
  executedAt?: unknown;
  orderId?: string;
};

const suffixes = ["USDT", "USDC", "USD"];

type AsterPairDetail = {
  selection: TradeSelection;
  focusAtMs?: number;
  averageEntry?: number | null;
  selectedActionId?: string;
  status?: "OPEN" | "CLOSED";
  pnl?: number | null;
  quantity?: number | null;
  dcaCount?: number | null;
  currentPrice?: number | null;
  exitPrice?: number | null;
};

function averageEntry(position: OpenPosition | null) {
  return finite(position?.averageEntry) ?? finite(position?.entryPrice);
}


function normalizedSymbol(symbol = "") {
  return symbol.toUpperCase().replace(/[\/_-]/g, "");
}

function baseAsset(symbol = "") {
  const value = normalizedSymbol(symbol);
  return suffixes.reduce((v, suffix) => (v.endsWith(suffix) ? v.slice(0, -suffix.length) : v), value) || "?";
}

function finite(value: unknown) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function amount(value: unknown, signed = false) {
  const n = finite(value);
  if (n === null) return "—";
  return `${signed && n > 0 ? "+" : ""}${new Intl.NumberFormat("nl-NL", {
    minimumFractionDigits: 2,
    maximumFractionDigits: Math.abs(n) < 0.01 && n !== 0 ? 4 : 2,
  }).format(n)}`;
}

function money(value: unknown) {
  const n = finite(value);
  return n === null ? "—" : `$${amount(n)}`;
}

function percentage(value: unknown) {
  const n = finite(value);
  if (n === null) return "—";
  return `${n > 0 ? "+" : ""}${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n)}%`;
}

function exchangeTimestampMs(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) return value < 10_000_000_000 ? value * 1000 : value;
  if (typeof value === "string" && value.trim()) {
    const numeric = Number(value);
    if (Number.isFinite(numeric) && numeric > 0) return numeric < 10_000_000_000 ? numeric * 1000 : numeric;
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  if (value && typeof value === "object") {
    const row = value as Record<string, unknown>;
    const seconds = finite(row.seconds);
    const nanoseconds = finite(row.nanoseconds) || 0;
    if (seconds !== null && seconds > 0) return seconds * 1000 + Math.floor(nanoseconds / 1_000_000);
  }
  return 0;
}

function clockTime(value: unknown) {
  const timestamp = exchangeTimestampMs(value);
  if (timestamp <= 0) return "—";
  return new Intl.DateTimeFormat("nl-NL", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(timestamp));
}

function dateTime(value: unknown) {
  const timestamp = exchangeTimestampMs(value);
  if (timestamp <= 0) return "—";
  const date = new Date(timestamp);
  const day = new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "short", year: "numeric" }).format(date);
  const clock = new Intl.DateTimeFormat("nl-NL", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date);
  return `${day}, ${clock}`;
}

function sideKey(row: { symbol?: string; side?: string }) {
  return `${normalizedSymbol(row.symbol)}|${String(row.side || "").toUpperCase()}`;
}

function findOpenPosition(positions: OpenPosition[], row: Activity) {
  const key = sideKey(row);
  return positions.find((position) => sideKey(position) === key && (finite(position.quantity) || 0) > 0) || null;
}

function activityLeverage(trade: Activity, position: OpenPosition | null) {
  const direct = finite(trade.leverage);
  if (direct !== null && direct >= 1) return Math.round(direct);
  const live = finite(position?.leverage);
  return live !== null && live >= 1 ? Math.round(live) : null;
}

function openPositionMargin(position: OpenPosition | null) {
  if (!position) return null;
  const direct = finite(position.initialMarginUsd);
  if (direct !== null && direct > 0) return direct;
  const notional = finite(position.notionalUsd);
  const leverage = finite(position.leverage);
  if (notional !== null && notional > 0 && leverage !== null && leverage > 0) return notional / leverage;
  return direct === 0 && notional === 0 ? 0 : null;
}

function activityMargin(trade: Activity, position: OpenPosition | null, leverage: number | null) {
  for (const value of [trade.marginUsd, trade.initialMarginUsd]) {
    const direct = finite(value);
    if (direct !== null && direct > 0) return direct;
  }
  const live = openPositionMargin(position);
  if (live !== null) return live;
  if (leverage && leverage > 0) {
    const basis = finite(trade.costBasisUsd) ?? finite(trade.executedNotionalUsd);
    if (basis !== null && basis > 0) return basis / leverage;
  }
  return null;
}

function currentCycleOpenedAt(position: OpenPosition, entries: Activity[], exits: Activity[]) {
  if (position.openedAt) return position.openedAt;
  const key = sideKey(position);
  const events = [
    ...entries.filter((row) => sideKey(row) === key).map((row) => ({ ...row, delta: Math.abs(finite(row.quantity) || 0) })),
    ...exits.filter((row) => sideKey(row) === key).map((row) => ({ ...row, delta: -Math.abs(finite(row.quantity) || 0) })),
  ].sort((a, b) => activityTime(a) - activityTime(b) || stableActivityId(a).localeCompare(stableActivityId(b), "en"));
  let exposure = 0;
  let openedAt: string | number | undefined;
  for (const event of events) {
    const before = exposure;
    exposure = Math.max(0, exposure + event.delta);
    if (before <= 1e-12 && event.delta > 0) openedAt = event.executedAt || event.timestampMs;
    if (exposure <= 1e-12) openedAt = undefined;
  }
  return exposure > 1e-12 ? openedAt : undefined;
}

function CoinIcon({ symbol }: { symbol: string }) {
  const asset = baseAsset(symbol);
  return (
    <span className="recent-coin-icon">
      <img src={`https://assets.coincap.io/assets/icons/${asset.toLowerCase()}@2x.png`} alt="" loading="lazy" onError={(event) => { event.currentTarget.hidden = true; }} />
      <i>{asset.slice(0, 2)}</i>
    </span>
  );
}

function ClosePositionControl({ position, onClosed, compact = true }: { position: OpenPosition | null; onClosed: () => void; compact?: boolean }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const requestKey = useRef("");
  const pnl = finite(position?.unrealizedPnl) ?? 0;
  const tone = pnl > 0 ? "profit" : pnl < 0 ? "loss" : "neutral";
  const asset = baseAsset(position?.symbol);

  async function closePosition() {
    if (busy) return;
    if (!position?.symbol || !position?.side || !(finite(position.quantity) && Number(position.quantity) > 0)) return;
    setBusy(true);
    setMessage("");
    if (!requestKey.current) requestKey.current = crypto.randomUUID();
    try {
      await authenticatedRequest(`/api/exchanges/aster/positions/${encodeURIComponent(String(position.symbol))}/close`, {
        method: "POST",
        body: JSON.stringify({
          confirm: true,
          side: String(position.side).toUpperCase(),
          expected_quantity: Number(position.quantity),
          idempotency_key: requestKey.current,
        }),
      });
      setMessage("Positie is door Aster volledig gesloten.");
      setConfirming(false);
      await onClosed();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Sluiten is niet gelukt.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        className={`market-close ${tone} ${compact ? "compact" : ""}`}
        disabled={busy || !position}
        aria-disabled={busy || !position}
        title={position ? "Sluit deze actuele Aster-positie" : "Deze trade is niet meer als actuele positie open"}
        onClick={() => position && setConfirming(true)}
      >
        Close
      </button>
      {confirming && position && typeof document !== "undefined" && createPortal(
        <div className="market-close-modal" role="dialog" aria-modal="true" aria-labelledby="aster-close-title">
          <div>
            <h3 id="aster-close-title">Positie market sluiten</h3>
            <dl>
              <dt>Coin</dt><dd>{asset}</dd>
              <dt>Richting</dt><dd>{String(position.side).toUpperCase()}</dd>
              <dt>Actuele grootte</dt><dd>{amount(position.quantity)}</dd>
              <dt>Geschatte P&amp;L</dt><dd className={tone}>{amount(position.unrealizedPnl, true)}</dd>
            </dl>
            <p>De volledige resterende positie wordt tegen marktprijs gesloten.</p>
            <strong>Weet je zeker dat je deze volledige positie market wilt sluiten?</strong>
            <footer>
              <button type="button" disabled={busy} onClick={() => setConfirming(false)}>Annuleren</button>
              <button type="button" className={`market-close ${tone}`} disabled={busy} onClick={closePosition}>{busy ? "Sluiten…" : "Volledig market sluiten"}</button>
            </footer>
            {message && <small>{message}</small>}
          </div>
        </div>,
        document.body,
      )}
      {message && !confirming && <div className="market-close-message" role="status">{message}</div>}
    </>
  );
}

const RecentTradeRow = memo(function RecentTradeRow({ trade, closed, positions, onClosed, scanActions = [], onOpenDetail }: { trade: Activity; closed: boolean; positions: OpenPosition[]; onClosed: () => void; scanActions?: ScanAction[]; onOpenDetail: (detail: AsterPairDetail) => void }) {
  const asset = baseAsset(trade.symbol);
  const result = finite(closed ? trade.realizedPnlUsd : trade.unrealizedPnlUsd);
  const pct = reliableReturnPct(trade);
  const openPosition = closed ? null : findOpenPosition(positions, trade);
  const matchingScanAction = closed ? [...scanActions].reverse().find((action) => sideKey(action) === sideKey(trade) && scanActionLabel(action) === "verkocht") || null : null;
  const leverage = activityLeverage(trade, openPosition) ?? finite(matchingScanAction?.leverage);
  const margin = activityMargin(trade, openPosition, leverage) ?? finite(matchingScanAction?.marginUsd);
  const tone = result === null ? "neutral" : result >= 0 ? "profit" : "loss";
  return (
    <div className="recent-trade-row aster-seven-column-row" role="row">
      <button className="recent-pair recent-pair-button" role="cell" type="button" onClick={() => onOpenDetail({ selection: { id: String(trade.exchangeTradeId || trade.id || stableActivityId(trade)), symbol: normalizedSymbol(trade.symbol), exchange: "aster", side: String(trade.side || ""), closedAt: closed ? String(trade.closedAt || trade.executedAt || "") : undefined, openedAt: !closed ? String(trade.executedAt || "") : undefined, mark: finite(openPosition?.markPrice) ?? undefined }, focusAtMs: closed ? exchangeTimestampMs(trade.closedAt || trade.executedAt || trade.timestampMs) : undefined, averageEntry: averageEntry(openPosition), status: closed ? "CLOSED" : "OPEN", pnl: result, quantity: finite(trade.quantity) ?? finite(openPosition?.quantity), dcaCount: finite(openPosition?.dcaCount), currentPrice: finite(openPosition?.markPrice), exitPrice: closed ? null : undefined })}>
        <CoinIcon symbol={asset} />
        <span className="recent-pair-copy">
          <span className="recent-pair-title"><b>{asset}</b><span className={`recent-side ${String(trade.side).toLowerCase()}`}>{String(trade.side || "—").toUpperCase()}</span></span>
          <small><time dateTime={trade.executedAt}>{dateTime(trade.executedAt || trade.timestampMs)}</time></small>
        </span>
      </button>
      <span className="recent-leverage" role="cell">{leverage === null ? "—" : `${leverage}x`}</span>
      <span className="recent-close-cell" role="cell">{closed ? <span className="recent-close-status">{String(matchingScanAction?.kind || "").toUpperCase() === "FULL_TP" ? "TP" : "Gesloten"}</span> : <ClosePositionControl position={openPosition} onClosed={onClosed} />}</span>
      <span className="recent-margin" role="cell">{money(margin)}</span>
      <strong role="cell" className={tone}>{amount(result, true)}</strong>
      <strong role="cell" className={pct === null ? "neutral" : pct >= 0 ? "profit" : "loss"}>{percentage(pct)}</strong>
      <strong role="cell" className={tone}>{amount(result, true)}</strong>
    </div>
  );
});

function TradeRows({ rows, closed, positions, onClosed, scanActions = [], onOpenDetail }: { rows: Activity[]; closed: boolean; positions: OpenPosition[]; onClosed: () => void; scanActions?: ScanAction[]; onOpenDetail: (detail: AsterPairDetail) => void }) {
  return (
    <div className="recent-trades-body" role="rowgroup">
      {rows.length
        ? rows.map((trade) => <RecentTradeRow key={`${stableActivityId(trade)}:${trade.timestampMs || trade.executedAt}`} trade={trade} closed={closed} positions={positions} onClosed={onClosed} scanActions={scanActions} onOpenDetail={onOpenDetail} />)
        : <div className="recent-trades-empty">{closed ? "Nog geen uitgestapte trades" : "Nog geen ingestapte trades"}</div>}
    </div>
  );
}

function SevenColumnHead() {
  return (
    <div className="recent-trades-head aster-seven-column-head" role="row">
      <span>PAIR</span><span>LEV</span><span>CLOSE</span><span>MARGIN</span><span>HUIDIGE PNL</span><span>%</span><span>P&amp;L</span>
    </div>
  );
}

function RecentTradesCard({ title, rows, closed, liveState, positions, onClosed, scanActions = [], compactLimit = 5, onOpenDetail }: { title: string; rows: Activity[]; closed: boolean; liveState: string; positions: OpenPosition[]; onClosed: () => void; scanActions?: ScanAction[]; compactLimit?: number; onOpenDetail: (detail: AsterPairDetail) => void }) {
  const [showAll, setShowAll] = useState(false);
  const [loadedPages, setLoadedPages] = useState(1);
  const sorted = useMemo(() => sortedActivity(rows) as Activity[], [rows]);
  const compact = sorted.slice(0, compactLimit);
  const history = pageActivity(sorted, loadedPages, 100) as Activity[];
  const hasMore = history.length < sorted.length;
  const toggle = () => { setShowAll((value) => !value); setLoadedPages(1); };
  return (
    <article className={`recent-trades-card recent-flip-card ${showAll ? "is-flipped" : ""}`}>
      <div className="recent-flip-inner">
        <section className="recent-flip-face recent-flip-front" aria-hidden={showAll} inert={showAll ? true : undefined}>
          <header><div><h2>{title}</h2><span className={`recent-live ${liveState.toLowerCase()}`}>{liveState}</span></div><button type="button" onClick={toggle} aria-label={`Toon alle ${closed ? "uitgestapte" : "ingestapte"} trades`}>Toon alle <i>↻</i></button></header>
          <SevenColumnHead />
          <TradeRows rows={compact} closed={closed} positions={positions} onClosed={onClosed} scanActions={scanActions} onOpenDetail={onOpenDetail} />
        </section>
        <section className="recent-flip-face recent-flip-back" aria-hidden={!showAll} inert={!showAll ? true : undefined}>
          <header><div><h2>{closed ? "Alle uitgestapte trades" : "Alle ingestapte trades"}</h2><span className={`recent-live ${liveState.toLowerCase()}`}>{liveState}</span></div><button type="button" onClick={toggle}>Terug naar laatste {compactLimit} <i>↻</i></button></header>
          <div className="recent-trades-scroll"><SevenColumnHead /><TradeRows rows={history} closed={closed} positions={positions} onClosed={onClosed} scanActions={scanActions} onOpenDetail={onOpenDetail} />{hasMore && <button className="recent-load-more" type="button" onClick={() => setLoadedPages((value) => value + 1)}>Laad nog 100</button>}</div>
        </section>
      </div>
    </article>
  );
}

function TopProfitRow({ position, openedAt, onClosed, onOpenDetail }: { position: OpenPosition; openedAt?: unknown; onClosed: () => void; onOpenDetail: (detail: AsterPairDetail) => void }) {
  const pnl = finite(position.unrealizedPnl);
  const tone = pnl === null ? "neutral" : pnl > 0 ? "profit" : pnl < 0 ? "loss" : "neutral";
  const pct = authoritativePositionReturnPct(position);
  const asset = baseAsset(position.symbol);
  const leverage = finite(position.leverage);
  return (
    <div className="recent-trade-row top-profit-row aster-seven-column-row" role="row">
      <button className="recent-pair recent-pair-button" role="cell" type="button" onClick={() => onOpenDetail({ selection: { id: positionId(position), symbol: normalizedSymbol(position.symbol), exchange: "aster", side: String(position.side || ""), entry: averageEntry(position), mark: finite(position.markPrice) ?? undefined, dcaCount: finite(position.dcaCount) ?? undefined, openedAt: exchangeTimestampMs(openedAt) ? new Date(exchangeTimestampMs(openedAt)).toISOString() : undefined }, averageEntry: averageEntry(position), status: "OPEN", pnl, quantity: finite(position.quantity), dcaCount: finite(position.dcaCount), currentPrice: finite(position.markPrice) })}>
        <CoinIcon symbol={asset} />
        <span className="recent-pair-copy">
          <span className="recent-pair-title"><b>{asset}</b><span className={`recent-side ${String(position.side).toLowerCase()}`}>{String(position.side || "—").toUpperCase()}</span></span>
          <small><time dateTime={exchangeTimestampMs(openedAt) ? new Date(exchangeTimestampMs(openedAt)).toISOString() : undefined}>{dateTime(openedAt)}</time></small>
        </span>
      </button>
      <span className="recent-leverage" role="cell">{leverage === null ? "—" : `${Math.round(leverage)}x`}</span>
      <span className="recent-close-cell" role="cell"><ClosePositionControl position={position} onClosed={onClosed} /></span>
      <span className="recent-margin" role="cell">{money(openPositionMargin(position))}</span>
      <strong role="cell" className={tone}>{amount(pnl, true)}</strong>
      <strong role="cell" className={pct === null ? "neutral" : pct >= 0 ? "profit" : "loss"}>{percentage(pct)}</strong>
      <strong role="cell" className={tone}>{amount(pnl, true)}</strong>
    </div>
  );
}

function TopProfitCard({ rows, entries, exits, liveState, onClosed, onOpenDetail }: { rows: OpenPosition[]; entries: Activity[]; exits: Activity[]; liveState: string; onClosed: () => void; onOpenDetail: (detail: AsterPairDetail) => void }) {
  return (
    <article className="recent-trades-card top-profit-card">
      <section className="recent-flip-face">
        <header><div><h2>Top 5 hoogste profit</h2><span className={`recent-live ${liveState.toLowerCase()}`}>{liveState}</span></div></header>
        <SevenColumnHead />
        <div className="recent-trades-body" role="rowgroup">
          {rows.length
            ? rows.map((position) => <TopProfitRow key={positionId(position)} position={position} openedAt={currentCycleOpenedAt(position, entries, exits)} onClosed={onClosed} onOpenDetail={onOpenDetail} />)
            : <div className="recent-trades-empty">Geen actuele open posities beschikbaar</div>}
        </div>
      </section>
    </article>
  );
}

function scanActionLabel(action: ScanAction) {
  const kind = String(action.kind || "").toUpperCase();
  const orderAction = String(action.action || "").toUpperCase();
  if (orderAction === "CLOSE" || ["FULL_TP", "PARTIAL_TP", "TAKE_PROFIT_CLOSE", "RISK_REDUCE"].includes(kind)) return "verkocht";
  if (["ADD_DCA", "PROTECTION_INCREASE"].includes(kind)) return "bijgekocht";
  return "gekocht";
}

function ScanActionsCard({ rows, completedAt, positions, exits, onOpenDetail }: { rows: ScanAction[]; completedAt?: unknown; positions: OpenPosition[]; exits: Activity[]; onOpenDetail: (detail: AsterPairDetail) => void }) {
  return (
    <article className="recent-trades-card scan-actions-card">
      <section className="recent-flip-face">
        <header><div><h2>Laatste 15 scan acties</h2></div><small className="scan-last-time">Laatste scan {clockTime(completedAt)}</small></header>
        <div className="recent-trades-head aster-scan-head" role="row">
          <span>PAIR</span><span>ACTIE</span><span>NR</span><span>LEV</span><span>MARGIN</span><span>HUIDIGE PNL</span><span>TIJD</span>
        </div>
        <div className="recent-trades-body" role="rowgroup">
          {rows.length ? rows.slice(-15).reverse().map((action, index) => {
            const position = findOpenPosition(positions, action);
            const label = scanActionLabel(action);
            const exit = label === "verkocht" ? exits.find((row) => sideKey(row) === sideKey(action)) : null;
            const pnl = position ? finite(position.unrealizedPnl) : finite(exit?.realizedPnlUsd);
            const tone = pnl === null ? "neutral" : pnl >= 0 ? "profit" : "loss";
            const leverage = finite(action.leverage) ?? finite(position?.leverage);
            const margin = finite(action.marginUsd) ?? openPositionMargin(position);
            const dcaNumber = label === "bijgekocht" ? finite(action.dcaNumber) : null;
            return <div className="recent-trade-row aster-scan-row" role="row" key={`${String(action.clientOrderId || action.symbol || index)}:${index}`}>
              <button className="scan-pair recent-pair-button" role="cell" type="button" onClick={() => onOpenDetail({ selection: { id: String(action.clientOrderId || action.orderId || `${normalizedSymbol(action.symbol)}:${exchangeTimestampMs(action.executedAt)}`), symbol: normalizedSymbol(action.symbol), exchange: "aster", side: String(action.side || ""), mark: finite(position?.markPrice) ?? undefined, dcaCount: finite(position?.dcaCount) ?? undefined, closedAt: label === "verkocht" && exchangeTimestampMs(action.executedAt) ? new Date(exchangeTimestampMs(action.executedAt)).toISOString() : undefined }, focusAtMs: exchangeTimestampMs(action.executedAt), averageEntry: averageEntry(position), selectedActionId: String(action.clientOrderId || action.orderId || ""), status: label === "verkocht" ? "CLOSED" : "OPEN", pnl, quantity: finite(position?.quantity), dcaCount: finite(position?.dcaCount) ?? dcaNumber, currentPrice: finite(position?.markPrice) })}>{baseAsset(action.symbol)}</button>
              <span className={`scan-action ${label === "verkocht" ? "sold" : ""}`} role="cell">{label}</span>
              <span role="cell">{dcaNumber === null ? "—" : `#${Math.round(dcaNumber)}`}</span>
              <span role="cell">{leverage === null ? "—" : `${Math.round(leverage)}x`}</span>
              <span role="cell">{money(margin)}</span>
              <strong role="cell" className={tone}>{amount(pnl, true)}</strong>
              <time role="cell" dateTime={exchangeTimestampMs(action.executedAt) ? new Date(exchangeTimestampMs(action.executedAt)).toISOString() : undefined}>{clockTime(action.executedAt)}</time>
            </div>;
          }) : <div className="recent-trades-empty">Nog geen uitgevoerde acties in de laatste scan</div>}
        </div>
      </section>
    </article>
  );
}

export function AsterRecentTrades({ snapshot, onRetry }: { snapshot: ExchangeSnapshot; onRetry: () => void }) {
  const [detail, setDetail] = useState<AsterPairDetail | null>(null);
  const scrollYRef = useRef(0);
  const lastTapRef = useRef(0);
  const openDetail = (next: AsterPairDetail) => { scrollYRef.current = window.scrollY; setDetail(next); };
  const closeDetail = () => { setDetail(null); requestAnimationFrame(() => window.scrollTo({ top: scrollYRef.current, behavior: "auto" })); };
  const handleDetailTouchEnd = () => { const now = Date.now(); if (now - lastTapRef.current < 320) closeDetail(); lastTapRef.current = now; };
  const activity = snapshot.data?.recentTradeActivity && typeof snapshot.data.recentTradeActivity === "object"
    ? snapshot.data.recentTradeActivity as Record<string, unknown>
    : {};
  const entries = useMemo(() => sortedActivity(Array.isArray(activity.entries) ? activity.entries : []) as Activity[], [activity.entries]);
  const exits = useMemo(() => sortedActivity(Array.isArray(activity.exits) ? activity.exits : []) as Activity[], [activity.exits]);
  const allPositions = useMemo(() => (Array.isArray(snapshot.data?.positions) ? snapshot.data.positions : []) as OpenPosition[], [snapshot.data?.positions]);
  const positions = useMemo(() => topProfitPositions(allPositions) as OpenPosition[], [allPositions]);
  const strategy2 = snapshot.data?.strategy2 && typeof snapshot.data.strategy2 === "object" ? snapshot.data.strategy2 as Record<string, unknown> : {};
  const orderQueue = strategy2.orderQueue && typeof strategy2.orderQueue === "object" ? strategy2.orderQueue as Record<string, unknown> : {};
  const scanActions = useMemo(() => (Array.isArray(orderQueue.lastScanActions) ? orderQueue.lastScanActions : []) as ScanAction[], [orderQueue.lastScanActions]);
  const liveState = snapshot.error ? "Offline" : snapshot.loading ? "Reconnecting" : snapshot.updatedAt && Date.now() - snapshot.updatedAt < 90_000 ? "Live" : "Delayed";
  if (snapshot.error && !entries.length && !exits.length) return <section className="recent-trades-error"><span>Tradegegevens tijdelijk niet beschikbaar</span><button type="button" onClick={onRetry}>Opnieuw proberen</button></section>;
  return (
    <section className={`aster-recent-trades aster-pair-detail-shell ${detail ? "is-detail-open" : ""}`} aria-label="Recente Aster trades">
      <div className="aster-pair-detail-inner">
        <div className="aster-pair-detail-front" aria-hidden={Boolean(detail)} inert={detail ? true : undefined}>
          <TopProfitCard rows={positions} entries={entries} exits={exits} liveState={liveState} onClosed={onRetry} onOpenDetail={openDetail} />
          <ScanActionsCard rows={scanActions} completedAt={orderQueue.lastScanCompletedAt} positions={allPositions} exits={exits} onOpenDetail={openDetail} />
          <RecentTradesCard title="Laatste 5 uitgestapte trades" rows={exits} closed liveState={liveState} positions={allPositions} onClosed={onRetry} scanActions={scanActions} compactLimit={5} onOpenDetail={openDetail} />
          <RecentTradesCard title="Laatste 5 ingestapte trades" rows={entries} closed={false} liveState={liveState} positions={allPositions} onClosed={onRetry} compactLimit={5} onOpenDetail={openDetail} />
        </div>
        <div className="aster-pair-detail-back" aria-hidden={!detail} inert={!detail ? true : undefined} onDoubleClick={closeDetail} onTouchEnd={handleDetailTouchEnd}>
          {detail && <>
            <header className="aster-pair-detail-header"><div><span>ASTER · TRADEDETAIL</span><h2>{detail.selection.symbol.replace(/USDT$/, "")} <i>/ USDT</i></h2><small>{String(detail.selection.side || "").toUpperCase()} · dubbel tikken om terug te gaan</small></div><button type="button" onClick={closeDetail} aria-label="Terug naar Aster">×</button></header>
            <SafeTradingChart selection={detail.selection} mode="aster-detail" focusAtMs={detail.focusAtMs} averageEntry={detail.averageEntry ?? undefined} selectedActionId={detail.selectedActionId} />
            <div className="aster-pair-summary" aria-label="Positiedetails">
              <div><span>Positie</span><strong className={detail.status === "OPEN" ? "profit" : "neutral"}>{detail.status || "—"}</strong></div>
              <div><span>Entry prijs (gem.)</span><strong>{money(detail.averageEntry)}</strong></div>
              <div><span>{detail.status === "CLOSED" ? "Exit prijs" : "Huidige prijs"}</span><strong>{money(detail.status === "CLOSED" ? detail.exitPrice : detail.currentPrice)}</strong></div>
              <div><span>{detail.status === "CLOSED" ? "Realized P&L" : "Unrealized P&L"}</span><strong className={(detail.pnl ?? 0) >= 0 ? "profit" : "loss"}>{money(detail.pnl)}</strong></div>
              <div><span>Aantal DCA</span><strong>{detail.dcaCount === null || detail.dcaCount === undefined ? "—" : Math.round(detail.dcaCount)}</strong></div>
              <div><span>Totale hoeveelheid</span><strong>{detail.quantity === null || detail.quantity === undefined ? "—" : amount(detail.quantity)}</strong></div>
            </div>
          </>}
        </div>
      </div>
    </section>
  );
}
