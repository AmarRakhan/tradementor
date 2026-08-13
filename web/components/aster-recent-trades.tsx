"use client";

import { memo, useMemo, useState } from "react";
import type { ExchangeSnapshot } from "@/lib/use-exchange-data";

type Activity = { id?: string; symbol?: string; side?: string; strategy?: string; executedNotionalUsd?: number; currentValueUsd?: number | null; unrealizedPnlUsd?: number | null; costBasisUsd?: number; closedValueUsd?: number; realizedPnlUsd?: number; timestampMs?: number; executedAt?: string };
const suffixes = ["USDT", "USDC", "USD"];
function baseAsset(symbol = "") { const value = symbol.toUpperCase().replace(/[\/_-]/g, ""); return suffixes.reduce((v, suffix) => v.endsWith(suffix) ? v.slice(0, -suffix.length) : v, value) || "?"; }
function amount(value: unknown, signed = false) { if (value === null || value === undefined || value === "") return "—"; const n = Number(value); if (!Number.isFinite(n)) return "—"; return `${signed && n > 0 ? "+" : ""}${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: Math.abs(n) < .01 && n !== 0 ? 4 : 2 }).format(n)}`; }
function time(value: unknown) { const date = new Date(String(value || "")); return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat("nl-NL", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date) : "—"; }

function activityTime(row: Activity) { const direct = Number(row.timestampMs); if (Number.isFinite(direct) && direct > 0) return direct; const parsed = Date.parse(String(row.executedAt || "")); return Number.isFinite(parsed) ? parsed : 0; }

function CoinIcon({ symbol }: { symbol: string }) { const asset = baseAsset(symbol); return <span className="recent-coin-icon"><img src={`https://assets.coincap.io/assets/icons/${asset.toLowerCase()}@2x.png`} alt="" loading="lazy" onError={(event) => { event.currentTarget.hidden = true; }} /><i>{asset.slice(0, 2)}</i></span>; }

const RecentTradeRow = memo(function RecentTradeRow({ trade, closed }: { trade: Activity; closed: boolean }) {
  const asset = baseAsset(trade.symbol); const result = Number(closed ? trade.realizedPnlUsd : trade.unrealizedPnlUsd); const hasResult = Number.isFinite(result);
  return <div className="recent-trade-row" role="row"><div className="recent-pair" role="cell"><CoinIcon symbol={asset} /><span><b>{asset}</b><small>Perp · {trade.strategy || "Niet aan strategie gekoppeld"}</small></span></div><div role="cell"><span className={`recent-side ${String(trade.side).toLowerCase()}`}>{String(trade.side || "—").toUpperCase()}</span></div><strong role="cell">{amount(closed ? trade.costBasisUsd : trade.executedNotionalUsd)}</strong><strong role="cell">{amount(closed ? trade.closedValueUsd : trade.currentValueUsd)}</strong><strong role="cell" className={hasResult ? result >= 0 ? "profit" : "loss" : ""}>{amount(hasResult ? result : null, true)}</strong><time role="cell" dateTime={trade.executedAt}>{time(trade.executedAt)}</time></div>;
});

function RecentTradesCard({ title, rows, closed, liveState }: { title: string; rows: Activity[]; closed: boolean; liveState: string }) {
  const [expanded, setExpanded] = useState(false); const visible = expanded ? rows.slice(0, 20) : rows.slice(0, 8); const toggle = () => setExpanded((value) => !value);
  return <article className="recent-trades-card"><header><div><h2>{title}</h2><span className={`recent-live ${liveState.toLowerCase()}`}>{liveState}</span></div><button type="button" onClick={toggle}>Bekijk alle 20 <i>→</i></button></header><div className="recent-trades-head" role="row"><span>PAIR</span><span>TYPE</span><span>{closed ? "INGEKOCHT ($)" : "INGESTAPT ($)"}</span><span>{closed ? "VERKOCHT ($)" : "NU WAARD ($)"}</span><span>{closed ? "RESULTAAT ($)" : "VERSCHIL ($)"}</span><span>TIJD</span></div><div className="recent-trades-body" role="rowgroup">{visible.length ? visible.map((trade, index) => <RecentTradeRow key={`${trade.id || trade.symbol}:${trade.executedAt}:${index}`} trade={trade} closed={closed} />) : <div className="recent-trades-empty">{closed ? "Nog geen uitgestapte trades" : "Nog geen ingestapte trades"}</div>}</div>{rows.length > 8 && <button className="recent-trades-toggle" type="button" onClick={toggle}>{expanded ? "Toon minder ↑" : "Toon alle 20 ↓"}</button>}</article>;
}

export function AsterRecentTrades({ snapshot, onRetry }: { snapshot: ExchangeSnapshot; onRetry: () => void }) {
  const activity = snapshot.data?.recentTradeActivity && typeof snapshot.data.recentTradeActivity === "object" ? snapshot.data.recentTradeActivity as Record<string, unknown> : {};
  const entries = useMemo(() => (Array.isArray(activity.entries) ? activity.entries as Activity[] : []).slice().sort((a, b) => activityTime(b) - activityTime(a)).slice(0, 20), [activity.entries]);
  const exits = useMemo(() => (Array.isArray(activity.exits) ? activity.exits as Activity[] : []).slice().sort((a, b) => activityTime(b) - activityTime(a)).slice(0, 20), [activity.exits]);
  const liveState = snapshot.error ? "Offline" : snapshot.loading ? "Reconnecting" : snapshot.updatedAt && Date.now() - snapshot.updatedAt < 45_000 ? "Live" : "Delayed";
  if (snapshot.error && !entries.length && !exits.length) return <section className="recent-trades-error"><span>Tradegegevens tijdelijk niet beschikbaar</span><button type="button" onClick={onRetry}>Opnieuw proberen</button></section>;
  return <section className="aster-recent-trades" aria-label="Recente Aster trades"><RecentTradesCard title="Laatste 20 ingestapte trades" rows={entries} closed={false} liveState={liveState} /><RecentTradesCard title="Laatste 20 uitgestapte trades" rows={exits} closed liveState={liveState} /></section>;
}
