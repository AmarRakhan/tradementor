"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  maxLeverage: number | null;
  bbStatus: BbStatus | null;
  bbUpper: number | null;
  bbMiddle: number | null;
  bbLower: number | null;
};

type MarketsPayload = { marketCount: number; updatedAt: number; interval: Timeframe; markets: MarketRow[] };
type EnrichedRow = Pick<MarketRow, "symbol" | "maxLeverage" | "bbStatus" | "bbUpper" | "bbMiddle" | "bbLower">;
type EnrichmentPayload = { markets: EnrichedRow[]; errors?: Array<{ symbol: string; detail: string }>; updatedAt: number };

const TIMEFRAMES: Timeframe[] = ["1m", "5m", "15m", "1h", "4h", "1d"];
const BB_FILTERS: Array<{ id: BbFilter; label: string }> = [
  { id: "all", label: "Alle" },
  { id: "above", label: "Boven upper" },
  { id: "between", label: "Tussen banden" },
  { id: "below", label: "Onder lower" },
];
const BB_RANK: Record<BbStatus, number> = { above: 3, between: 2, below: 1 };
const ENRICH_BATCH_SIZE = 8;

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

function classifyBb(livePrice: number, upper: number | null, lower: number | null, fallback: BbStatus | null) {
  if (upper === null || lower === null) return fallback;
  return livePrice > upper ? "above" as const : livePrice < lower ? "below" as const : "between" as const;
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
  const [enriching, setEnriching] = useState(false);
  const [error, setError] = useState("");
  const generationRef = useRef(0);

  const enrich = useCallback(async (base: MarketsPayload, generation: number) => {
    setEnriching(true);
    let partialFailures = 0;
    try {
      const symbols = base.markets.map((row) => row.symbol);
      for (let index = 0; index < symbols.length; index += ENRICH_BATCH_SIZE) {
        if (generationRef.current !== generation) return;
        const batch = symbols.slice(index, index + ENRICH_BATCH_SIZE);
        try {
          const payload = await authenticatedRequest(`/api/markets/aster?mode=enrich&interval=${encodeURIComponent(base.interval)}&symbols=${encodeURIComponent(batch.join(","))}`) as EnrichmentPayload;
          if (generationRef.current !== generation) return;
          if (!payload || !Array.isArray(payload.markets)) throw new Error("Markets-enrichment heeft een ongeldig formaat");
          partialFailures += Array.isArray(payload.errors) ? payload.errors.length : 0;
          const updates = new Map(payload.markets.map((row) => [row.symbol, row]));
          setData((current) => {
            if (!current || current.interval !== base.interval) return current;
            return {
              ...current,
              updatedAt: Math.max(current.updatedAt, payload.updatedAt || 0),
              markets: current.markets.map((row) => {
                const update = updates.get(row.symbol);
                return update ? { ...row, ...update, bbStatus: classifyBb(row.lastPrice, update.bbUpper, update.bbLower, update.bbStatus) } : row;
              }),
            };
          });
        } catch {
          partialFailures += batch.length;
        }
      }
      if (generationRef.current === generation && partialFailures > 0) {
        setError(`${partialFailures} markt${partialFailures === 1 ? "" : "en"} kon${partialFailures === 1 ? "" : "den"} nog niet volledig worden aangevuld.`);
      }
    } finally {
      if (generationRef.current === generation) setEnriching(false);
    }
  }, []);

  const load = useCallback(async (background = false, runEnrichment = true) => {
    const generation = runEnrichment ? ++generationRef.current : generationRef.current;
    background ? setRefreshing(true) : setLoading(true);
    setError("");
    try {
      const payload = await authenticatedRequest(`/api/markets/aster?mode=base&interval=${encodeURIComponent(timeframe)}`) as MarketsPayload;
      if (!payload || !Array.isArray(payload.markets)) throw new Error("Markets-response heeft een ongeldig formaat");
      if (runEnrichment && generationRef.current !== generation) return;

      setData((current) => {
        if (!current || current.interval !== payload.interval) return payload;
        const oldBySymbol = new Map(current.markets.map((row) => [row.symbol, row]));
        return {
          ...payload,
          markets: payload.markets.map((fresh) => {
            const old = oldBySymbol.get(fresh.symbol);
            if (!old) return fresh;
            return {
              ...fresh,
              maxLeverage: old.maxLeverage,
              bbUpper: old.bbUpper,
              bbMiddle: old.bbMiddle,
              bbLower: old.bbLower,
              bbStatus: classifyBb(fresh.lastPrice, old.bbUpper, old.bbLower, old.bbStatus),
            };
          }),
        };
      });
      setLoading(false);
      setRefreshing(false);
      if (runEnrichment) void enrich(payload, generation);
    } catch (reason) {
      if (runEnrichment && generationRef.current !== generation) return;
      setError(reason instanceof Error ? reason.message : "Markets kon niet worden geladen");
      setLoading(false);
      setRefreshing(false);
      if (runEnrichment) setEnriching(false);
    }
  }, [enrich, timeframe]);

  useEffect(() => { void load(false, true); }, [load]);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load(true, false);
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const enrichedCount = useMemo(() => (data?.markets || []).filter((row) => row.maxLeverage !== null && row.bbStatus !== null).length, [data]);

  const rows = useMemo(() => {
    const normalized = query.trim().toUpperCase();
    const filtered = (data?.markets || []).filter((row) => !normalized || row.symbol.includes(normalized) || row.baseAsset.includes(normalized))
      .filter((row) => bbFilter === "all" || row.bbStatus === bbFilter);
    const direction = sortDirection === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      if ((sortKey === "leverage" && (a.maxLeverage === null || b.maxLeverage === null)) || (sortKey === "bb" && (a.bbStatus === null || b.bbStatus === null))) {
        const aReady = sortKey === "leverage" ? a.maxLeverage !== null : a.bbStatus !== null;
        const bReady = sortKey === "leverage" ? b.maxLeverage !== null : b.bbStatus !== null;
        if (aReady !== bReady) return aReady ? -1 : 1;
      }
      let delta = 0;
      if (sortKey === "volume") delta = a.quoteVolume24h - b.quoteVolume24h;
      else if (sortKey === "change") delta = a.change24hPct - b.change24hPct;
      else if (sortKey === "leverage") delta = (a.maxLeverage || 0) - (b.maxLeverage || 0);
      else if (a.bbStatus && b.bbStatus) delta = BB_RANK[a.bbStatus] - BB_RANK[b.bbStatus];
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
      <button type="button" className={styles.refresh} onClick={() => void load(true, false)} disabled={loading || refreshing}>{refreshing ? "Verversen…" : "↻ Vernieuwen"}</button>
    </header>

    <div className={styles.controlCard}>
      <label className={styles.search}><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search symbol" aria-label="Search symbol" /></label>
      <div className={styles.timeframes} role="group" aria-label="Bollinger timeframe">{TIMEFRAMES.map((value) => <button key={value} type="button" className={timeframe === value ? styles.active : ""} onClick={() => setTimeframe(value)}>{value}</button>)}</div>
      <div className={styles.bbFilters} role="group" aria-label="Bollinger Band filter">{BB_FILTERS.map((item) => <button key={item.id} type="button" className={bbFilter === item.id ? styles.activeFilter : ""} onClick={() => setBbFilter(item.id)}>{item.label}</button>)}</div>
    </div>

    <div className={styles.meta}><span>{data ? `${data.marketCount} tradable markten` : "Aster markten"}</span><span>BB 20 · 2σ · {timeframe}</span><span>{enriching && data ? `Data ${enrichedCount}/${data.marketCount}` : `Update ${updated}`}</span></div>

    <div className={styles.sortBar} role="group" aria-label="Markets sortering">
      <button type="button" onClick={() => chooseSort("volume")} className={sortKey === "volume" ? styles.activeSort : ""}>Volume {arrow("volume")}</button>
      <button type="button" onClick={() => chooseSort("change")} className={sortKey === "change" ? styles.activeSort : ""}>24h {arrow("change")}</button>
      <button type="button" onClick={() => chooseSort("leverage")} className={sortKey === "leverage" ? styles.activeSort : ""}>Leverage {arrow("leverage")}</button>
      <button type="button" onClick={() => chooseSort("bb")} className={sortKey === "bb" ? styles.activeSort : ""}>BB {arrow("bb")}</button>
    </div>

    {loading && !data ? <div className={styles.state}><div className={styles.spinner} /><strong>Aster Markets laden</strong><span>Actieve USDT-perpetuals en realtime tickerdata worden opgehaald.</span></div>
      : error && !data ? <div className={`${styles.state} ${styles.error}`}><strong>Markets tijdelijk niet beschikbaar</strong><span>{error}</span><button type="button" onClick={() => void load(false, true)}>Opnieuw proberen</button></div>
      : rows.length === 0 && enriching && bbFilter !== "all" ? <div className={styles.state}><div className={styles.spinner} /><strong>Bollinger-data veilig aanvullen</strong><span>De marktdata is al zichtbaar; BB-data wordt bewust gedoseerd opgehaald om Aster rate-limits te respecteren.</span></div>
      : rows.length === 0 ? <div className={styles.state}><strong>Geen markten gevonden</strong><span>Pas je zoekterm of Bollinger-filter aan.</span></div>
      : <div className={styles.list} aria-live="polite">{rows.map((row) => <article key={row.symbol} className={styles.row}>
          <div className={styles.identity}><span className={styles.coin}>{row.baseAsset.slice(0, 2)}</span><div><div className={styles.symbolLine}><strong>{row.symbol}</strong><em>{row.maxLeverage !== null ? `${row.maxLeverage}x` : "—"}</em></div><small>Vol {compactUsd(row.quoteVolume24h)}</small></div></div>
          <div className={styles.marketPrice}><strong>${price(row.lastPrice)}</strong><span className={row.change24hPct > 0 ? styles.positive : row.change24hPct < 0 ? styles.negative : ""}>{signedPercent(row.change24hPct)}</span></div>
          {row.bbStatus && row.bbUpper !== null && row.bbMiddle !== null && row.bbLower !== null
            ? <div className={`${styles.bbBadge} ${styles[row.bbStatus]}`} title={`Upper ${price(row.bbUpper)} · Mid ${price(row.bbMiddle)} · Lower ${price(row.bbLower)}`}><i />{statusLabel(row.bbStatus)}</div>
            : <div className={styles.bbBadge} title="Bollinger-data wordt veilig gedoseerd opgehaald"><i />BB laden</div>}
        </article>)}</div>}
    {error && data && <div className={styles.staleWarning}>{error}</div>}
  </section>;
}
