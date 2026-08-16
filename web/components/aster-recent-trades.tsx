"use client";

import { memo, useMemo, useState } from "react";
import type { ExchangeSnapshot } from "@/lib/use-exchange-data";
import { pageActivity, reliableReturnPct, sortedActivity, stableActivityId } from "@/lib/recent-trades.mjs";

type Activity = { id?: string; exchangeTradeId?: string; symbol?: string; side?: string; realizedPnlUsd?: number; unrealizedPnlUsd?: number | null; returnPct?: number | null; roePct?: number | null; roiPct?: number | null; timestampMs?: number; executedAt?: string };
const suffixes = ["USDT", "USDC", "USD"];
function baseAsset(symbol = "") { const value = symbol.toUpperCase().replace(/[\/_-]/g, ""); return suffixes.reduce((v, suffix) => v.endsWith(suffix) ? v.slice(0, -suffix.length) : v, value) || "?"; }
function amount(value: unknown, signed = false) { if (value === null || value === undefined || value === "") return "—"; const n = Number(value); if (!Number.isFinite(n)) return "—"; return `${signed && n > 0 ? "+" : ""}${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: Math.abs(n) < .01 && n !== 0 ? 4 : 2 }).format(n)}`; }
function percentage(value: unknown) { if (value === null || value === undefined || value === "") return "—"; const n = Number(value); if (!Number.isFinite(n)) return "—"; return `${n > 0 ? "+" : ""}${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n)}%`; }
function dateTime(value: unknown) { const date = new Date(String(value || "")); return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date).replace(/ om /, " · ") : "—"; }

function CoinIcon({ symbol }: { symbol: string }) { const asset = baseAsset(symbol); return <span className="recent-coin-icon"><img src={`https://assets.coincap.io/assets/icons/${asset.toLowerCase()}@2x.png`} alt="" loading="lazy" onError={(event) => { event.currentTarget.hidden = true; }} /><i>{asset.slice(0, 2)}</i></span>; }

const RecentTradeRow = memo(function RecentTradeRow({ trade, closed }: { trade: Activity; closed: boolean }) {
  const asset = baseAsset(trade.symbol); const result = Number(closed ? trade.realizedPnlUsd : trade.unrealizedPnlUsd); const hasResult = Number.isFinite(result); const pct = reliableReturnPct(trade);
  return <div className="recent-trade-row" role="row">
    <div className="recent-pair" role="cell">
      <CoinIcon symbol={asset} />
      <span className="recent-pair-copy">
        <span className="recent-pair-title"><b>{asset}</b><span className={`recent-side ${String(trade.side).toLowerCase()}`}>{String(trade.side || "—").toUpperCase()}</span></span>
        <small><time dateTime={trade.executedAt}>{dateTime(trade.executedAt)}</time></small>
      </span>
    </div>
    <strong role="cell" className={pct === null ? "" : pct >= 0 ? "profit" : "loss"}>{percentage(pct)}</strong>
    <strong role="cell" className={hasResult ? result >= 0 ? "profit" : "loss" : ""}>{amount(hasResult ? result : null, true)}</strong>
  </div>;
});

function TradeRows({ rows, closed }: { rows: Activity[]; closed: boolean }) {
  return <div className="recent-trades-body" role="rowgroup">{rows.length ? rows.map((trade) => <RecentTradeRow key={`${stableActivityId(trade)}:${trade.timestampMs || trade.executedAt}`} trade={trade} closed={closed} />) : <div className="recent-trades-empty">{closed ? "Nog geen uitgestapte trades" : "Nog geen ingestapte trades"}</div>}</div>;
}

function RecentTradesCard({ title, rows, closed, liveState }: { title: string; rows: Activity[]; closed: boolean; liveState: string }) {
  const [showAll, setShowAll] = useState(false); const [loadedPages, setLoadedPages] = useState(1); const sorted = useMemo(() => sortedActivity(rows) as Activity[], [rows]); const compact = sorted.slice(0, 20); const history = pageActivity(sorted, loadedPages, 100) as Activity[]; const hasMore = history.length < sorted.length;
  const toggle = () => { setShowAll((value) => !value); setLoadedPages(1); };
  return <article className={`recent-trades-card recent-flip-card ${showAll ? "is-flipped" : ""}`}>
    <div className="recent-flip-inner">
      <section className="recent-flip-face recent-flip-front" aria-hidden={showAll} inert={showAll ? true : undefined}>
        <header><div><h2>{title}</h2><span className={`recent-live ${liveState.toLowerCase()}`}>{liveState}</span></div><button type="button" onClick={toggle} aria-label={`Toon alle ${closed ? "uitgestapte" : "ingestapte"} trades`}>Toon alle <i>↻</i></button></header>
        <div className="recent-trades-head" role="row"><span>PAIR · TYPE · TIJD</span><span>%</span><span>P&amp;L</span></div><TradeRows rows={compact} closed={closed} />
      </section>
      <section className="recent-flip-face recent-flip-back" aria-hidden={!showAll} inert={!showAll ? true : undefined}>
        <header><div><h2>{closed ? "Alle uitgestapte trades" : "Alle ingestapte trades"}</h2><span className={`recent-live ${liveState.toLowerCase()}`}>{liveState}</span></div><button type="button" onClick={toggle}>Terug naar laatste 20 <i>↻</i></button></header>
        <div className="recent-trades-scroll"><div className="recent-trades-head" role="row"><span>PAIR · TYPE · TIJD</span><span>%</span><span>P&amp;L</span></div><TradeRows rows={history} closed={closed} />{hasMore && <button className="recent-load-more" type="button" onClick={() => setLoadedPages((value) => value + 1)}>Laad nog 100</button>}</div>
      </section>
    </div>
  </article>;
}

export function AsterRecentTrades({ snapshot, onRetry }: { snapshot: ExchangeSnapshot; onRetry: () => void }) {
  const activity = snapshot.data?.recentTradeActivity && typeof snapshot.data.recentTradeActivity === "object" ? snapshot.data.recentTradeActivity as Record<string, unknown> : {};
  const entries = useMemo(() => sortedActivity(Array.isArray(activity.entries) ? activity.entries : []) as Activity[], [activity.entries]);
  const exits = useMemo(() => sortedActivity(Array.isArray(activity.exits) ? activity.exits : []) as Activity[], [activity.exits]);
  const liveState = snapshot.error ? "Offline" : snapshot.loading ? "Reconnecting" : snapshot.updatedAt && Date.now() - snapshot.updatedAt < 45_000 ? "Live" : "Delayed";
  if (snapshot.error && !entries.length && !exits.length) return <section className="recent-trades-error"><span>Tradegegevens tijdelijk niet beschikbaar</span><button type="button" onClick={onRetry}>Opnieuw proberen</button></section>;
  return <section className="aster-recent-trades" aria-label="Recente Aster trades"><RecentTradesCard title="Laatste 20 uitgestapte trades" rows={exits} closed liveState={liveState} /><RecentTradesCard title="Laatste 20 ingestapte trades" rows={entries} closed={false} liveState={liveState} /></section>;
}
