"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import styles from "./markets-page.module.css";

type Timeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
type BbStatus = "above" | "between" | "below";
type BbFilter = "all" | BbStatus;
type SortKey = "volume" | "change" | "leverage" | "bb";
type SortDirection = "asc" | "desc";

type MarketRow = {
  symbol: string;
  baseAsset: string;
  lastPrice: number;
  change24hPct: number;
  quoteVolume24h: number;
  maxLeverage: number;
  bbStatus: BbStatus;
  bbUpper: number;
  bbMiddle: number;
  bbLower: number;
};

type MarketsPayload = { marketCount: number; updatedAt: number; interval: Timeframe; markets: MarketRow[] };

const TIMEFRAMES: Timeframe[] = ["1m", "5m", "15m", "1h", "4h", "1d"];
const BB_FILTERS: Array<{ id: BbFilter; label: string }> = [
  { id: "all", label: "Alle" },
  { id: "above", label: "Boven upper" },
  { id: "between", label: "Tussen banden" },
  { id: "below", label: "Onder lower" },
];
const BB_RANK: Record<BbStatus, number> = { above: 3, between: 2, below: 1 };

function compactUsd(value: number) {
  return new Intl.NumberFormat("nl-NL", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function price(value: number) {
  const digits = value >= 1000 ? 2 : value >= 1 ? 4 : value >= .01 ? 5 : 7;
  return new Intl.NumberFormat("en-US", { minimumFractionDigits: 0, maximumFractionDigits: digits }).format(value);
}

function signedPercent(value: number) {
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function statusLabel(status: BbStatus) {
  return status === "above" ? "Above Upper" : status === "below" ? "Below Lower" : "Between Bands";
}

export function MarketsPage() {
  const [timeframe, setTimeframe] = useState<Timeframe>("15m");
  const [query, setQuery] = useState("");
  const [bbFilter, setBbFilter] = useState<BbFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("volume");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [data, setData] = useState<MarketsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async (background = false) => {
    background ? setRefreshing(true) : setLoading(true);
    setError("");
    try {
      const payload = await authenticatedRequest(`/api/markets/aster?interval=${encodeURIComponent(timeframe)}`) as MarketsPayload;
      if (!payload || !Array.isArray(payload.markets)) throw new Error("Markets-response heeft een ongeldig formaat");
      setData(payload);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Markets kon niet worden geladen");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [timeframe]);

  useEffect(() => { void load(false); }, [load]);
  useEffect(() => {
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") void load(true); }, 60_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const rows = useMemo(() => {
    const normalized = query.trim().toUpperCase();
    const filtered = (data?.markets || []).filter((row) => !normalized || row.symbol.includes(normalized) || row.baseAsset.includes(normalized))
      .filter((row) => bbFilter === "all" || row.bbStatus === bbFilter);
    const direction = sortDirection === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      let delta = 0;
      if (sortKey === "volume") delta = a.quoteVolume24h - b.quoteVolume24h;
      else if (sortKey === "change") delta = a.change24hPct - b.change24hPct;
      else if (sortKey === "leverage") delta = a.maxLeverage - b.maxLeverage;
      else delta = BB_RANK[a.bbStatus] - BB_RANK[b.bbStatus];
      return delta * direction || a.symbol.localeCompare(b.symbol);
    });
  }, [data, query, bbFilter, sortKey, sortDirection]);

  const chooseSort = (key: SortKey) => {
    if (sortKey === key) setSortDirection((value) => value === "desc" ? "asc" : "desc");
    else { setSortKey(key); setSortDirection("desc"); }
  };
  const arrow = (key: SortKey) => sortKey === key ? (sortDirection === "desc" ? "↓" : "↑") : "↕";
  const updated = data?.updatedAt ? new Date(data.updatedAt).toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";

  return <section className={styles.page} aria-labelledby="markets-title">
    <header className={styles.heading}>
      <div><span className={styles.eyebrow}>ASTER · USDT PERPETUALS</span><h1 id="markets-title">Markets</h1><p>Realtime markten, leverage en Bollinger-status op één mobiel overzicht.</p></div>
      <button type="button" className={styles.refresh} onClick={() => void load(true)} disabled={loading || refreshing}>{refreshing ? "Verversen…" : "↻ Vernieuwen"}</button>
    </header>

    <div className={styles.controlCard}>
      <label className={styles.search}><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search symbol" aria-label="Search symbol" /></label>
      <div className={styles.timeframes} role="group" aria-label="Bollinger timeframe">{TIMEFRAMES.map((value) => <button key={value} type="button" className={timeframe === value ? styles.active : ""} onClick={() => setTimeframe(value)}>{value}</button>)}</div>
      <div className={styles.bbFilters} role="group" aria-label="Bollinger Band filter">{BB_FILTERS.map((item) => <button key={item.id} type="button" className={bbFilter === item.id ? styles.activeFilter : ""} onClick={() => setBbFilter(item.id)}>{item.label}</button>)}</div>
    </div>

    <div className={styles.meta}><span>{data ? `${data.marketCount} tradable markten` : "Aster markten"}</span><span>BB 20 · 2σ · {timeframe}</span><span>Update {updated}</span></div>

    <div className={styles.sortBar} role="group" aria-label="Markets sortering">
      <button type="button" onClick={() => chooseSort("volume")} className={sortKey === "volume" ? styles.activeSort : ""}>Volume {arrow("volume")}</button>
      <button type="button" onClick={() => chooseSort("change")} className={sortKey === "change" ? styles.activeSort : ""}>24h {arrow("change")}</button>
      <button type="button" onClick={() => chooseSort("leverage")} className={sortKey === "leverage" ? styles.activeSort : ""}>Leverage {arrow("leverage")}</button>
      <button type="button" onClick={() => chooseSort("bb")} className={sortKey === "bb" ? styles.activeSort : ""}>BB {arrow("bb")}</button>
    </div>

    {loading && !data ? <div className={styles.state}><div className={styles.spinner} /><strong>Aster Markets laden</strong><span>Tradable perpetuals, leverage en {timeframe}-candles worden gecontroleerd.</span></div>
      : error && !data ? <div className={`${styles.state} ${styles.error}`}><strong>Markets tijdelijk niet beschikbaar</strong><span>{error}</span><button type="button" onClick={() => void load(false)}>Opnieuw proberen</button></div>
      : rows.length === 0 ? <div className={styles.state}><strong>Geen markten gevonden</strong><span>Pas je zoekterm of Bollinger-filter aan.</span></div>
      : <div className={styles.list} aria-live="polite">{rows.map((row) => <article key={row.symbol} className={styles.row}>
          <div className={styles.identity}><span className={styles.coin}>{row.baseAsset.slice(0, 2)}</span><div><div className={styles.symbolLine}><strong>{row.symbol}</strong><em>{row.maxLeverage}x</em></div><small>Vol {compactUsd(row.quoteVolume24h)}</small></div></div>
          <div className={styles.marketPrice}><strong>${price(row.lastPrice)}</strong><span className={row.change24hPct > 0 ? styles.positive : row.change24hPct < 0 ? styles.negative : ""}>{signedPercent(row.change24hPct)}</span></div>
          <div className={`${styles.bbBadge} ${styles[row.bbStatus]}`} title={`Upper ${price(row.bbUpper)} · Mid ${price(row.bbMiddle)} · Lower ${price(row.bbLower)}`}><i />{statusLabel(row.bbStatus)}</div>
        </article>)}</div>}
    {error && data && <div className={styles.staleWarning}>Laatste betrouwbare snapshot blijft zichtbaar. Nieuwe refresh: {error}</div>}
  </section>;
}
