"use client";

import { memo, useMemo, useRef, useState } from "react";
import type { ExchangeSnapshot } from "@/lib/use-exchange-data";
import { authenticatedRequest } from "@/lib/cloud-client";
import { activityTime, pageActivity, reliableReturnPct, sortedActivity, stableActivityId } from "@/lib/recent-trades.mjs";
import { authoritativePositionReturnPct, positionId, topProfitPositions } from "@/lib/top-profit-positions.mjs";

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
  openedAt?: string | number;
};

const suffixes = ["USDT", "USDC", "USD"];

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

function dateTime(value: unknown) {
  const date = new Date(String(value || ""));
  if (!Number.isFinite(date.getTime())) return "—";
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

function activityMargin(trade: Activity, position: OpenPosition | null, leverage: number | null) {
  for (const value of [trade.marginUsd, trade.initialMarginUsd]) {
    const direct = finite(value);
    if (direct !== null && direct >= 0) return direct;
  }
  const live = finite(position?.initialMarginUsd);
  if (live !== null && live >= 0) return live;
  if (leverage && leverage > 0) {
    const basis = finite(trade.costBasisUsd) ?? finite(trade.executedNotionalUsd);
    if (basis !== null && basis >= 0) return basis / leverage;
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
      {confirming && position && (
        <div className="market-close-modal" role="dialog" aria-modal="true">
          <div>
            <h3>Positie market sluiten</h3>
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
        </div>
      )}
      {message && !confirming && <div className="market-close-message" role="status">{message}</div>}
    </>
  );
}

const RecentTradeRow = memo(function RecentTradeRow({ trade, closed, positions, onClosed }: { trade: Activity; closed: boolean; positions: OpenPosition[]; onClosed: () => void }) {
  const asset = baseAsset(trade.symbol);
  const result = finite(closed ? trade.realizedPnlUsd : trade.unrealizedPnlUsd);
  const pct = reliableReturnPct(trade);
  const openPosition = closed ? null : findOpenPosition(positions, trade);
  const leverage = activityLeverage(trade, openPosition);
  const margin = activityMargin(trade, openPosition, leverage);
  const tone = result === null ? "neutral" : result >= 0 ? "profit" : "loss";
  return (
    <div className="recent-trade-row aster-six-column-row" role="row">
      <div className="recent-pair" role="cell">
        <CoinIcon symbol={asset} />
        <span className="recent-pair-copy">
          <span className="recent-pair-title"><b>{asset}</b><span className={`recent-side ${String(trade.side).toLowerCase()}`}>{String(trade.side || "—").toUpperCase()}</span></span>
          <small><time dateTime={trade.executedAt}>{dateTime(trade.executedAt || trade.timestampMs)}</time></small>
        </span>
      </div>
      <span className="recent-leverage" role="cell">{leverage === null ? "—" : `${leverage}x`}</span>
      <span className="recent-close-cell" role="cell"><ClosePositionControl position={openPosition} onClosed={onClosed} /></span>
      <span className="recent-margin" role="cell">{money(margin)}</span>
      <strong role="cell" className={pct === null ? "neutral" : pct >= 0 ? "profit" : "loss"}>{percentage(pct)}</strong>
      <strong role="cell" className={tone}>{amount(result, true)}</strong>
    </div>
  );
});

function TradeRows({ rows, closed, positions, onClosed }: { rows: Activity[]; closed: boolean; positions: OpenPosition[]; onClosed: () => void }) {
  return (
    <div className="recent-trades-body" role="rowgroup">
      {rows.length
        ? rows.map((trade) => <RecentTradeRow key={`${stableActivityId(trade)}:${trade.timestampMs || trade.executedAt}`} trade={trade} closed={closed} positions={positions} onClosed={onClosed} />)
        : <div className="recent-trades-empty">{closed ? "Nog geen uitgestapte trades" : "Nog geen ingestapte trades"}</div>}
    </div>
  );
}

function SixColumnHead() {
  return (
    <div className="recent-trades-head aster-six-column-head" role="row">
      <span>PAIR</span><span>LEV</span><span>CLOSE</span><span>MARGIN</span><span>%</span><span>P&amp;L</span>
    </div>
  );
}

function RecentTradesCard({ title, rows, closed, liveState, positions, onClosed, compactLimit = 5 }: { title: string; rows: Activity[]; closed: boolean; liveState: string; positions: OpenPosition[]; onClosed: () => void; compactLimit?: number }) {
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
          <SixColumnHead />
          <TradeRows rows={compact} closed={closed} positions={positions} onClosed={onClosed} />
        </section>
        <section className="recent-flip-face recent-flip-back" aria-hidden={!showAll} inert={!showAll ? true : undefined}>
          <header><div><h2>{closed ? "Alle uitgestapte trades" : "Alle ingestapte trades"}</h2><span className={`recent-live ${liveState.toLowerCase()}`}>{liveState}</span></div><button type="button" onClick={toggle}>Terug naar laatste {compactLimit} <i>↻</i></button></header>
          <div className="recent-trades-scroll"><SixColumnHead /><TradeRows rows={history} closed={closed} positions={positions} onClosed={onClosed} />{hasMore && <button className="recent-load-more" type="button" onClick={() => setLoadedPages((value) => value + 1)}>Laad nog 100</button>}</div>
        </section>
      </div>
    </article>
  );
}

function TopProfitRow({ position, openedAt, onClosed }: { position: OpenPosition; openedAt?: string | number; onClosed: () => void }) {
  const pnl = finite(position.unrealizedPnl);
  const tone = pnl === null ? "neutral" : pnl > 0 ? "profit" : pnl < 0 ? "loss" : "neutral";
  const pct = authoritativePositionReturnPct(position);
  const asset = baseAsset(position.symbol);
  const leverage = finite(position.leverage);
  return (
    <div className="recent-trade-row top-profit-row aster-six-column-row" role="row">
      <div className="recent-pair" role="cell">
        <CoinIcon symbol={asset} />
        <span className="recent-pair-copy">
          <span className="recent-pair-title"><b>{asset}</b><span className={`recent-side ${String(position.side).toLowerCase()}`}>{String(position.side || "—").toUpperCase()}</span></span>
          <small><time dateTime={String(openedAt || "")}>{dateTime(openedAt)}</time></small>
        </span>
      </div>
      <span className="recent-leverage" role="cell">{leverage === null ? "—" : `${Math.round(leverage)}x`}</span>
      <span className="recent-close-cell" role="cell"><ClosePositionControl position={position} onClosed={onClosed} /></span>
      <span className="recent-margin" role="cell">{money(position.initialMarginUsd)}</span>
      <strong role="cell" className={pct === null ? "neutral" : pct >= 0 ? "profit" : "loss"}>{percentage(pct)}</strong>
      <strong role="cell" className={tone}>{amount(pnl, true)}</strong>
    </div>
  );
}

function TopProfitCard({ rows, entries, exits, liveState, onClosed }: { rows: OpenPosition[]; entries: Activity[]; exits: Activity[]; liveState: string; onClosed: () => void }) {
  return (
    <article className="recent-trades-card top-profit-card">
      <section className="recent-flip-face">
        <header><div><h2>Top 5 hoogste profit</h2><span className={`recent-live ${liveState.toLowerCase()}`}>{liveState}</span></div></header>
        <SixColumnHead />
        <div className="recent-trades-body" role="rowgroup">
          {rows.length
            ? rows.map((position) => <TopProfitRow key={positionId(position)} position={position} openedAt={currentCycleOpenedAt(position, entries, exits)} onClosed={onClosed} />)
            : <div className="recent-trades-empty">Geen actuele open posities beschikbaar</div>}
        </div>
      </section>
    </article>
  );
}

export function AsterRecentTrades({ snapshot, onRetry }: { snapshot: ExchangeSnapshot; onRetry: () => void }) {
  const activity = snapshot.data?.recentTradeActivity && typeof snapshot.data.recentTradeActivity === "object"
    ? snapshot.data.recentTradeActivity as Record<string, unknown>
    : {};
  const entries = useMemo(() => sortedActivity(Array.isArray(activity.entries) ? activity.entries : []) as Activity[], [activity.entries]);
  const exits = useMemo(() => sortedActivity(Array.isArray(activity.exits) ? activity.exits : []) as Activity[], [activity.exits]);
  const allPositions = useMemo(() => (Array.isArray(snapshot.data?.positions) ? snapshot.data.positions : []) as OpenPosition[], [snapshot.data?.positions]);
  const positions = useMemo(() => topProfitPositions(allPositions) as OpenPosition[], [allPositions]);
  const liveState = snapshot.error ? "Offline" : snapshot.loading ? "Reconnecting" : snapshot.updatedAt && Date.now() - snapshot.updatedAt < 45_000 ? "Live" : "Delayed";
  if (snapshot.error && !entries.length && !exits.length) return <section className="recent-trades-error"><span>Tradegegevens tijdelijk niet beschikbaar</span><button type="button" onClick={onRetry}>Opnieuw proberen</button></section>;
  return (
    <section className="aster-recent-trades" aria-label="Recente Aster trades">
      <TopProfitCard rows={positions} entries={entries} exits={exits} liveState={liveState} onClosed={onRetry} />
      <RecentTradesCard title="Laatste 5 ingestapte trades" rows={entries} closed={false} liveState={liveState} positions={allPositions} onClosed={onRetry} compactLimit={5} />
      <RecentTradesCard title="Laatste 5 uitgestapte trades" rows={exits} closed liveState={liveState} positions={allPositions} onClosed={onRetry} compactLimit={5} />
    </section>
  );
}
