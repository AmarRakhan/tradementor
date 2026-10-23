"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { currentAsterPositions, subscribeAsterPositions } from "@/lib/aster-positions-feed";
import {
  MARKET_BB_LABEL,
  MARKET_BB_TIMEFRAMES,
  bbStatusFor,
  compactVolume,
  filterMarkets,
  ownershipBySymbol,
  signedPercent,
  sortMarkets,
  type MarketBbStatus,
  type MarketBbTimeframe,
  type MarketCategory,
  type MarketOwnerFilter,
  type MarketRow,
  type MarketSortKey,
} from "@/lib/markets-universe.mjs";
import { MarketsCoinFlip } from "@/components/markets-coin-flip";
import { MarketIcon } from "@/components/market-icon";
import styles from "./markets-page.module.css";

// Build 640: Markets in Black Luxe — every tradable Aster perpetual, one row per
// market, BOT/MANUAL labels from the account snapshot, double tap flips a row to
// its full-screen Koers chart.

type MarketsPayload = { marketCount: number; updatedAt: number; interval: MarketBbTimeframe; markets: MarketRow[] };
type EnrichedRow = Pick<MarketRow, "symbol" | "maxLeverage" | "bbStatus" | "bbUpper" | "bbMiddle" | "bbLower">;
type EnrichmentPayload = { markets: EnrichedRow[]; errors?: Array<{ symbol: string; detail: string }>; updatedAt: number };
type SortDirection = "asc" | "desc";
type FlipState = { row: MarketRow; rect: DOMRect } | null;

const OWNER_CHIPS: Array<{ id: MarketOwnerFilter; label: string }> = [
  { id: "all", label: "Alles" }, { id: "free", label: "Vrij" }, { id: "position", label: "In positie" }, { id: "bot", label: "BOT" }, { id: "manual", label: "MANUAL" },
];
const CATEGORY_CHIPS: Array<{ id: MarketCategory | "all"; label: string }> = [
  { id: "all", label: "Alle" }, { id: "crypto", label: "Crypto" }, { id: "stock", label: "Aandelen" }, { id: "commodity", label: "Grondstoffen" },
];
const BB_FILTERS: Array<{ id: MarketBbStatus | "all"; label: string }> = [
  { id: "all", label: "Alle" }, { id: "above", label: "Upper" }, { id: "between", label: "Binnen" }, { id: "below", label: "Lower" },
];
const BB_TEXT: Record<MarketBbStatus, string> = { above: "UPPER", between: "BINNEN", below: "LOWER" };
const ENRICH_BATCH_SIZE = 8;
const DOUBLE_TAP_MS = 300;
const FAVORITES_KEY = "tradementor.markets.favorites";
const PREFS_KEY = "tradementor.markets.prefs.v640";

function readJson<T>(key: string, fallback: T): T {
  try { const raw = window.localStorage.getItem(key); return raw ? JSON.parse(raw) as T : fallback; } catch { return fallback; }
}
function writeJson(key: string, value: unknown) {
  try { window.localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
}

function SortArrows({ active, direction }: { active: boolean; direction: SortDirection }) {
  return <svg className={styles.sortArrows} viewBox="0 0 10 16" aria-hidden="true">
    <path d="M5 1.5 8.5 6h-7Z" className={active && direction === "asc" ? styles.arrowOn : ""} />
    <path d="M5 14.5 1.5 10h7Z" className={active && direction === "desc" ? styles.arrowOn : ""} />
  </svg>;
}

function BbBars({ status }: { status: MarketBbStatus | null }) {
  return <span className={`${styles.bbBars} ${status ? styles[`bb_${status}`] : styles.bb_loading}`} aria-hidden="true"><i /><i /><i /></span>;
}

export function MarketsPage() {
  const [timeframe, setTimeframe] = useState<MarketBbTimeframe>("15m");
  const [query, setQuery] = useState("");
  const [owner, setOwner] = useState<MarketOwnerFilter>("all");
  const [category, setCategory] = useState<MarketCategory | "all">("all");
  const [bbFilter, setBbFilter] = useState<MarketBbStatus | "all">("all");
  const [sortKey, setSortKey] = useState<MarketSortKey>("change");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [favorites, setFavorites] = useState<Set<string>>(() => new Set());
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [data, setData] = useState<MarketsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [positions, setPositions] = useState<unknown[]>(() => currentAsterPositions());
  const [flip, setFlip] = useState<FlipState>(null);
  const generationRef = useRef(0);
  const orderRef = useRef<string[]>([]);
  const enrichedRef = useRef<Set<string>>(new Set());
  const leverageRef = useRef<Map<string, number>>(new Map());
  const tapRef = useRef<{ symbol: string; at: number; timer: number } | null>(null);
  const restoredRef = useRef(false);

  // Restore filters and favorites once.
  useEffect(() => {
    setFavorites(new Set(readJson<string[]>(FAVORITES_KEY, [])));
    const prefs = readJson<Partial<{ timeframe: MarketBbTimeframe; owner: MarketOwnerFilter; category: MarketCategory | "all"; bbFilter: MarketBbStatus | "all"; sortKey: MarketSortKey; sortDirection: SortDirection; favoritesOnly: boolean }>>(PREFS_KEY, {});
    if (prefs.timeframe && (MARKET_BB_TIMEFRAMES as readonly string[]).includes(prefs.timeframe)) setTimeframe(prefs.timeframe);
    if (prefs.owner) setOwner(prefs.owner);
    if (prefs.category) setCategory(prefs.category);
    if (prefs.bbFilter) setBbFilter(prefs.bbFilter);
    if (prefs.sortKey) setSortKey(prefs.sortKey);
    if (prefs.sortDirection) setSortDirection(prefs.sortDirection);
    if (typeof prefs.favoritesOnly === "boolean") setFavoritesOnly(prefs.favoritesOnly);
    restoredRef.current = true;
  }, []);
  useEffect(() => {
    if (!restoredRef.current) return;
    writeJson(PREFS_KEY, { timeframe, owner, category, bbFilter, sortKey, sortDirection, favoritesOnly });
  }, [timeframe, owner, category, bbFilter, sortKey, sortDirection, favoritesOnly]);
  useEffect(() => subscribeAsterPositions(setPositions), []);

  const ownership = useMemo(() => ownershipBySymbol(positions), [positions]);

  const enrich = useCallback(async (interval: MarketBbTimeframe, generation: number, fallbackOrder: string[]) => {
    let failures = 0;
    for (;;) {
      if (generationRef.current !== generation) return;
      // The shown order once it exists (what you see fills first), else the server order.
      const order = orderRef.current.length ? orderRef.current : fallbackOrder;
      const batch = order.filter((symbol) => !enrichedRef.current.has(symbol)).slice(0, ENRICH_BATCH_SIZE);
      if (!batch.length) break;
      batch.forEach((symbol) => enrichedRef.current.add(symbol));
      try {
        const payload = await authenticatedRequest(`/api/markets/aster?mode=enrich&interval=${encodeURIComponent(interval)}&symbols=${encodeURIComponent(batch.join(","))}`) as EnrichmentPayload;
        if (generationRef.current !== generation) return;
        if (!payload || !Array.isArray(payload.markets)) throw new Error("Ongeldige Markets-aanvulling");
        failures += Array.isArray(payload.errors) ? payload.errors.length : 0;
        const updates = new Map(payload.markets.map((row) => [row.symbol, row]));
        for (const row of payload.markets) if (row.maxLeverage) leverageRef.current.set(row.symbol, row.maxLeverage);
        setData((current) => current && current.interval === interval ? {
          ...current,
          markets: current.markets.map((row) => {
            const update = updates.get(row.symbol);
            return update ? { ...row, ...update, bbStatus: bbStatusFor(row.lastPrice, update.bbUpper, update.bbLower, update.bbStatus) } : row;
          }),
        } : current);
      } catch {
        failures += batch.length;
      }
    }
    if (generationRef.current === generation && failures > 0) setError(`${failures} markt${failures === 1 ? "" : "en"} nog zonder Bollinger-data.`);
  }, []);

  const load = useCallback(async (background: boolean) => {
    const generation = background ? generationRef.current : ++generationRef.current;
    if (!background) { setLoading(true); enrichedRef.current = new Set(); }
    try {
      const payload = await authenticatedRequest(`/api/markets/aster?mode=base&interval=${encodeURIComponent(timeframe)}`) as MarketsPayload;
      if (!payload || !Array.isArray(payload.markets)) throw new Error("Markets-antwoord heeft een ongeldig formaat");
      if (generationRef.current !== generation) return;
      setError("");
      setData((current) => {
        const keep = current && current.interval === payload.interval ? new Map(current.markets.map((row) => [row.symbol, row])) : null;
        return {
          ...payload,
          markets: payload.markets.map((fresh) => {
            const old = keep?.get(fresh.symbol);
            const maxLeverage = leverageRef.current.get(fresh.symbol) ?? fresh.maxLeverage ?? null;
            return old ? { ...fresh, maxLeverage, bbUpper: old.bbUpper, bbMiddle: old.bbMiddle, bbLower: old.bbLower, bbStatus: bbStatusFor(fresh.lastPrice, old.bbUpper, old.bbLower, old.bbStatus) } : { ...fresh, maxLeverage };
          }),
        };
      });
      setLoading(false);
      if (!background) window.setTimeout(() => void enrich(payload.interval, generation, payload.markets.map((row) => row.symbol)), 0);
    } catch (reason) {
      if (generationRef.current !== generation) return;
      setError(reason instanceof Error ? reason.message : "Markets kon niet worden geladen");
      setLoading(false);
    }
  }, [enrich, timeframe]);

  useEffect(() => { void load(false); }, [load]);
  useEffect(() => {
    const timer = window.setInterval(() => { if (document.visibilityState === "visible" && !flip) void load(true); }, 30_000);
    return () => window.clearInterval(timer);
  }, [load, flip]);

  const rows = useMemo(() => sortMarkets(
    filterMarkets(data?.markets || [], { query, owner, category, bb: bbFilter, ownership, favorites, favoritesOnly }),
    sortKey, sortDirection,
  ), [data, query, owner, category, bbFilter, ownership, favorites, favoritesOnly, sortKey, sortDirection]);

  // Enrich in the order the rows are shown, so what you see fills first.
  useEffect(() => {
    const shown = rows.map((row) => row.symbol);
    const rest = (data?.markets || []).map((row) => row.symbol).filter((symbol) => !shown.includes(symbol));
    orderRef.current = [...shown, ...rest];
  }, [rows, data]);

  const chooseSort = (key: MarketSortKey) => {
    if (sortKey === key) setSortDirection((value) => value === "desc" ? "asc" : "desc");
    else { setSortKey(key); setSortDirection(key === "symbol" ? "asc" : "desc"); }
  };
  const toggleFavorite = (symbol: string) => {
    setFavorites((current) => {
      const next = new Set(current);
      if (next.has(symbol)) next.delete(symbol); else next.add(symbol);
      writeJson(FAVORITES_KEY, [...next]);
      return next;
    });
  };
  const openMarket = (row: MarketRow) => {
    const url = new URL(window.location.href); url.searchParams.delete("tmView"); url.searchParams.set("tmSymbol", row.symbol); url.searchParams.set("tmTimeframe", timeframe); url.hash = "/aster";
    window.history.pushState({ destination: "aster", market: row.symbol, timeframe }, "", `${url.pathname}${url.search}${url.hash}`);
    window.dispatchEvent(new CustomEvent("tradementor:open-aster-market", { detail: { symbol: row.symbol, timeframe } }));
    window.dispatchEvent(new PopStateEvent("popstate", { state: window.history.state }));
  };
  // One tap opens the Tradecentrum (as before); a double tap flips the row to its Koers chart.
  const onRowTap = (row: MarketRow, event: ReactMouseEvent<HTMLElement>) => {
    const now = Date.now();
    const target = event.currentTarget;
    const last = tapRef.current;
    if (last && last.symbol === row.symbol && now - last.at < DOUBLE_TAP_MS) {
      window.clearTimeout(last.timer);
      tapRef.current = null;
      setFlip({ row, rect: target.getBoundingClientRect() });
      return;
    }
    if (last) window.clearTimeout(last.timer);
    const timer = window.setTimeout(() => { tapRef.current = null; openMarket(row); }, DOUBLE_TAP_MS);
    tapRef.current = { symbol: row.symbol, at: now, timer };
  };
  useEffect(() => () => { if (tapRef.current) window.clearTimeout(tapRef.current.timer); }, []);

  const bbLabel = MARKET_BB_LABEL[timeframe];
  const activeFilterCount = Number(bbFilter !== "all") + Number(favoritesOnly) + Number(timeframe !== "15m");

  return <section className={styles.page} aria-labelledby="markets-title">
    <header className={styles.top}>
      <h1 id="markets-title" className={styles.title}>Markets<span className={loading ? styles.dotIdle : styles.dot} aria-label={loading ? "Laden" : "Live"} /></h1>
      <label className={styles.search}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.6" /><path d="m20 20-4.2-4.2" /></svg>
        <input id="markets-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Zoek munt of symbool" aria-label="Zoek munt of symbool" autoComplete="off" spellCheck={false} />
      </label>
      <button type="button" className={styles.filterButton} onClick={() => setSheetOpen(true)} aria-label="Filters en Bollinger-timeframe" aria-haspopup="dialog">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h11M19 17h1" /><circle cx="15" cy="7" r="2" /><circle cx="9" cy="12" r="2" /><circle cx="17" cy="17" r="2" /></svg>
        {activeFilterCount ? <b>{activeFilterCount}</b> : null}
      </button>
    </header>

    <div className={styles.chips}>
      <div role="group" aria-label="Positie" className={styles.chipGroup}>
        {OWNER_CHIPS.map((chip) => <button key={chip.id} type="button" aria-pressed={owner === chip.id} className={owner === chip.id ? styles.chipActive : styles.chip} onClick={() => setOwner(chip.id)}>{chip.label}</button>)}
      </div>
      <span className={styles.chipDivider} aria-hidden="true" />
      <div role="group" aria-label="Categorie" className={styles.chipGroup}>
        {CATEGORY_CHIPS.map((chip) => <button key={chip.id} type="button" aria-pressed={category === chip.id} className={category === chip.id ? styles.chipActive : styles.chip} onClick={() => setCategory(chip.id)}>{chip.label}</button>)}
      </div>
    </div>

    <div className={styles.table}>
      <div className={styles.head} role="group" aria-label="Sorteren">
        <button type="button" className={styles.headSymbol} onClick={() => chooseSort("symbol")} aria-pressed={sortKey === "symbol"}>SYMBOL<SortArrows active={sortKey === "symbol"} direction={sortDirection} /></button>
        <button type="button" className={styles.headVol} onClick={() => chooseSort("volume")} aria-pressed={sortKey === "volume"}>24H VOL<SortArrows active={sortKey === "volume"} direction={sortDirection} /></button>
        <button type="button" className={styles.headBb} onClick={() => chooseSort("bb")} aria-pressed={sortKey === "bb"}>BB ({bbLabel})<SortArrows active={sortKey === "bb"} direction={sortDirection} /></button>
        <button type="button" className={styles.headChange} onClick={() => chooseSort("change")} aria-pressed={sortKey === "change"}>24H<SortArrows active={sortKey === "change"} direction={sortDirection} /></button>
        <span aria-hidden="true" />
      </div>

      {loading && !data ? <div className={styles.state}><span className={styles.spinner} /><strong>Markets laden</strong></div>
        : error && !data ? <div className={styles.state}><strong>Markets tijdelijk niet beschikbaar</strong><span>{error}</span><button type="button" onClick={() => void load(false)}>Opnieuw proberen</button></div>
        : rows.length === 0 ? <div className={styles.state}><strong>Geen markten gevonden</strong><span>Pas je zoekterm of filter aan.</span></div>
        : <ul className={styles.list} aria-label={`${rows.length} markten`}>
          {rows.map((row) => {
            const own = ownership.get(row.symbol);
            const favorite = favorites.has(row.symbol);
            const up = row.change24hPct > 0, down = row.change24hPct < 0;
            return <li key={row.symbol} className={styles.row} data-market-symbol={row.symbol}>
              <button type="button" className={styles.rowMain} onClick={(event) => onRowTap(row, event)} aria-label={`${row.baseAsset}${row.quoteAsset !== "USDT" ? ` ${row.quoteAsset}` : ""}: tik om te handelen, dubbeltik voor de koers`}>
                <span className={styles.cellSymbol}>
                  <span className={styles.iconWrap}>
                    <MarketIcon row={row} />
                    {row.quoteAsset !== "USDT" ? <em className={styles.quote}>{row.quoteAsset}</em> : null}
                  </span>
                  <span className={styles.nameLine}>
                    <strong>{row.baseAsset}</strong>
                    <small>{row.maxLeverage ? `${row.maxLeverage}x` : ""}</small>
                    {own?.bot ? <span className={styles.tagBot}>BOT</span> : null}
                    {own?.manual ? <span className={styles.tagManual}>MANUAL</span> : null}
                  </span>
                </span>
                <span className={styles.cellVol}>{compactVolume(row.quoteVolume24h)}</span>
                <span className={styles.cellBb}><BbBars status={row.bbStatus} /><span className={row.bbStatus ? styles[`bbText_${row.bbStatus}`] : styles.bbTextLoading}>{row.bbStatus ? BB_TEXT[row.bbStatus] : "···"}</span></span>
                <span className={up ? styles.changeUp : down ? styles.changeDown : styles.changeFlat}>{signedPercent(row.change24hPct)}</span>
              </button>
              <button type="button" className={favorite ? styles.starOn : styles.star} onClick={() => toggleFavorite(row.symbol)} aria-pressed={favorite} aria-label={favorite ? `${row.baseAsset} uit favorieten` : `${row.baseAsset} als favoriet`}>
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3.2 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17.2 6.6 20.1l1-6.1-4.4-4.3 6.1-.9Z" /></svg>
              </button>
            </li>;
          })}
        </ul>}
    </div>
    {error && data ? <p className={styles.note}>{error}</p> : null}
    {data ? <p className={styles.note}>{data.marketCount} handelbare perpetuals · tik om te handelen · dubbeltik voor de koers</p> : null}

    {sheetOpen ? <div className={styles.sheetBackdrop} onClick={() => setSheetOpen(false)}>
      <div className={styles.sheet} role="dialog" aria-modal="true" aria-labelledby="markets-filter-title" onClick={(event) => event.stopPropagation()}>
        <span className={styles.sheetHandle} aria-hidden="true" />
        <div className={styles.sheetHead}><h2 id="markets-filter-title">Filters</h2><button type="button" onClick={() => setSheetOpen(false)} aria-label="Sluiten">✕</button></div>
        <h3>Bollinger-timeframe</h3>
        <div className={styles.segment} role="group" aria-label="Bollinger-timeframe">
          {MARKET_BB_TIMEFRAMES.map((value) => <button key={value} type="button" aria-pressed={timeframe === value} className={timeframe === value ? styles.segmentOn : ""} onClick={() => setTimeframe(value)}>{MARKET_BB_LABEL[value]}</button>)}
        </div>
        <h3>Bollinger Bands 20 · 2σ</h3>
        <div className={styles.segment} role="group" aria-label="Bollinger-filter">
          {BB_FILTERS.map((item) => <button key={item.id} type="button" aria-pressed={bbFilter === item.id} className={bbFilter === item.id ? styles.segmentOn : ""} onClick={() => setBbFilter(item.id)}>{item.label}</button>)}
        </div>
        <label className={styles.switchRow}>
          <span><strong>Alleen favorieten</strong><small>Markten met een ster</small></span>
          <input type="checkbox" checked={favoritesOnly} onChange={(event) => setFavoritesOnly(event.target.checked)} />
          <i aria-hidden="true" />
        </label>
        <button type="button" className={styles.sheetDone} onClick={() => setSheetOpen(false)}>Klaar</button>
      </div>
    </div> : null}

    {flip ? <MarketsCoinFlip row={data?.markets.find((row) => row.symbol === flip.row.symbol) || flip.row} originRect={flip.rect} onClosed={() => setFlip(null)} /> : null}
  </section>;
}
