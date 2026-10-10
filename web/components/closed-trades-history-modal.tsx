"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { closedTradeDurationMs, closedTradeTime, uniqueClosedTrades, verifiedClosedTradeMargin } from "@/lib/closed-trades-history.mjs";

type ClosedTrade = {
  recordId?: string; exchangeTradeId?: string; symbol?: string; side?: string;
  realizedPnlUsd?: number | null; openedAt?: string | null; closedAt?: string | null;
  executedMarginUsd?: number | null; marginUsd?: number | null; initialMarginUsd?: number | null;
};
type HistoryPage = { closedTrades?: ClosedTrade[]; nextCursor?: string | null; hasMore?: boolean };
export type ClosedHistoryMode = "all" | "today";

const numeric = (value: unknown): number | null => value == null || value === "" || !Number.isFinite(Number(value)) ? null : Number(value);
const currency = (value: number | null) => value === null ? "Niet beschikbaar" : `US$ ${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Math.abs(value))}`;
const dayKey = (ms: number) => { const parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Amsterdam", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(ms); const get = (name: string) => parts.find(part => part.type === name)?.value ?? ""; return `${get("year")}-${get("month")}-${get("day")}`; };
const duration = (ms: number | null) => ms === null ? "Niet beschikbaar" : ms >= 86_400_000 ? `${Math.floor(ms / 86_400_000)}d ${Math.floor(ms % 86_400_000 / 3_600_000)}u` : ms >= 3_600_000 ? `${Math.floor(ms / 3_600_000)}u ${Math.floor(ms % 3_600_000 / 60_000)}m` : `${Math.floor(ms / 60_000)}m`;
const closedWhen = (ms: number | null) => ms === null ? "Tijd onbekend" : new Intl.DateTimeFormat("nl-NL", { timeZone: "Europe/Amsterdam", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(ms);

export function ClosedTradesHistoryModal({ mode, onClose, todayCount, todayTotal }: { mode: ClosedHistoryMode; onClose: () => void; todayCount: string; todayTotal: string }) {
  const [rows, setRows] = useState<ClosedTrade[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [flipped, setFlipped] = useState(false);
  const today = useMemo(() => dayKey(Date.now()), []);
  const showRows = useMemo(() => {
    const sorted = uniqueClosedTrades(rows);
    return mode === "today" ? sorted.filter(row => { const ms = closedTradeTime(row); return ms !== null && dayKey(ms) === today; }) : sorted;
  }, [mode, rows, today]);
  const reachedYesterday = mode === "today" && rows.some(row => {
    const ms = closedTradeTime(row);
    return ms !== null && dayKey(ms) < today;
  });
  const load = useCallback(async (next: string | null, signal?: AbortSignal) => {
    if (loading) return;
    setLoading(true); setError("");
    try {
      const query = new URLSearchParams({ limit: "30" });
      if (next) query.set("cursor", next);
      const page = await authenticatedRequest(`/api/exchanges/aster/closed-trades/history?${query}`, { cache: "no-store", signal }) as HistoryPage;
      if (signal?.aborted) return;
      if (!page || !Array.isArray(page.closedTrades)) throw new Error("Ongeldige historische gegevens ontvangen");
      setRows(previous => uniqueClosedTrades([...previous, ...page.closedTrades!]));
      setCursor(typeof page.nextCursor === "string" ? page.nextCursor : null);
      setHasMore(page.hasMore === true && Boolean(page.nextCursor));
    } catch (cause) {
      if (signal?.aborted) return;
      setError(cause instanceof Error ? cause.message : "Historie tijdelijk niet bereikbaar");
    } finally { if (!signal?.aborted) setLoading(false); }
  }, [loading]);

  useEffect(() => {
    const abort = new AbortController();
    setFlipped(false);
    const frame = requestAnimationFrame(() => setFlipped(true));
    void load(null, abort.signal);
    return () => { cancelAnimationFrame(frame); abort.abort(); };
    // Mounted once per modal opening. Page loads happen only on button press.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", escape);
    return () => { document.body.style.overflow = oldOverflow; window.removeEventListener("keydown", escape); };
  }, [onClose]);

  return <div className="aps-closed-overlay" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="aps-closed-perspective">
      <section className={`aps-closed-flip ${flipped ? "is-flipped" : ""}`} role="dialog" aria-modal="true" aria-label={mode === "all" ? "Gesloten resultaat" : "Trades gesloten vandaag"}>
        <div className="aps-closed-face aps-closed-front" aria-hidden="true"><span>✦</span><strong>{mode === "all" ? "GESLOTEN RESULTAAT" : "TRADES GESLOTEN"}</strong></div>
        <div className="aps-closed-face aps-closed-back">
          <header><div><small>✦ AMAR · TRADE HISTORIE</small><h2>{mode === "all" ? "Gesloten resultaat" : "Trades gesloten vandaag"}</h2><p>Nieuwste eerst · {mode === "all" ? "Volledige historie" : "Alleen vandaag"}</p></div><button type="button" aria-label="Sluiten" onClick={onClose}>×</button></header>
          {mode === "today" ? <div className="aps-closed-summary"><span>Gesloten vandaag <strong>{todayCount}</strong></span><span>Resultaat <strong>{todayTotal}</strong></span></div> : null}
          <div className="aps-closed-scroll">
            {showRows.map(row => {
              const close = closedTradeTime(row);
              const profit = numeric(row.realizedPnlUsd);
              const margin = verifiedClosedTradeMargin(row);
              return <article className="aps-closed-row" key={row.recordId || row.exchangeTradeId || `${row.symbol}:${row.side}:${row.closedAt}`}>
                <div className="aps-closed-row-head"><strong>{row.symbol || "Onbekend"}</strong><b className={row.side === "SHORT" ? "short" : "long"}>{row.side || "—"}</b><time>{closedWhen(close)}</time></div>
                <div className="aps-closed-row-grid"><span><small>Resultaat</small><strong className={profit === null ? "" : profit >= 0 ? "positive" : "negative"}>{profit !== null && profit >= 0 ? "+" : profit !== null ? "−" : ""}{currency(profit)}</strong></span><span><small>Marge</small><strong>{currency(margin)}</strong></span><span><small>Duur</small><strong>{duration(closedTradeDurationMs(row))}</strong></span></div>
              </article>;
            })}
            {loading ? <p role="status" className="aps-closed-message">Gesloten trades laden…</p> : null}
            {error ? <p role="alert" className="aps-closed-message">{error}</p> : null}
            {!loading && !error && showRows.length === 0 ? <p className="aps-closed-message">Geen bevestigde gesloten trades gevonden.</p> : null}
            {(hasMore && !reachedYesterday || error) && !loading ? <button type="button" className="aps-closed-more" onClick={() => void load(error && rows.length === 0 ? null : cursor)}>{error ? "Opnieuw proberen" : "Meer laden · oudere trades"}</button> : null}
          </div>
          <footer>Geregistreerde exchange-resultaten · ontbrekende gegevens worden niet geschat</footer>
        </div>
      </section>
    </div>
  </div>;
}
