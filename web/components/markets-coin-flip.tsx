"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";
import { CandlestickSeries, ColorType, CrosshairMode, LineSeries, TrackingModeExitMode, createChart, createSeriesMarkers, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { authenticatedRequest } from "@/lib/cloud-client";
import { PORTFOLIO_KOERS_TIMEFRAMES, bollinger20x2 } from "@/lib/portfolio-koers-chart.mjs";
import { formatMarketPrice, signedPercent, tradeMarkersFromEvents, type MarketRow } from "@/lib/markets-universe.mjs";
import styles from "./markets-coin-flip.module.css";

// Build 640: double tap on a Markets row flips that card to the coin's Koers
// chart — same look as Portfolio Koers on the Aster page, full screen, nothing
// above or below it. Double tap on the chart flips it back.

type Candle = { time: number; open: number; high: number; low: number; close: number };
type Timeframe = (typeof PORTFOLIO_KOERS_TIMEFRAMES)[number];
const INTERVAL: Record<string, string> = { "1m": "1m", "5m": "5m", "15m": "15m", "1u": "1h", "4u": "4h", "24u": "1d" };
const VIEW: Record<string, { visibleBars: number; barSpacing: number; rightOffset: number }> = {
  "1m": { visibleBars: 32, barSpacing: 7.2, rightOffset: 1.5 },
  "5m": { visibleBars: 31, barSpacing: 7.4, rightOffset: 1.5 },
  "15m": { visibleBars: 42, barSpacing: 5.4, rightOffset: 1.6 },
  "1u": { visibleBars: 42, barSpacing: 5.4, rightOffset: 1.6 },
  "4u": { visibleBars: 42, barSpacing: 5.4, rightOffset: 1.6 },
  "24u": { visibleBars: 36, barSpacing: 6.2, rightOffset: 1.6 },
};
const FLIP_MS = 640;
const DOUBLE_TAP_MS = 320;
const TIMEFRAME_KEY = "tradementor.markets.flip.timeframe";

function parseCandles(payload: unknown): Candle[] {
  const rows = Array.isArray((payload as { candles?: unknown[] })?.candles) ? (payload as { candles: unknown[] }).candles : [];
  const out: Candle[] = [];
  for (const raw of rows) {
    const row = raw as Record<string, unknown>;
    const candle = { time: Math.floor(Number(row.time)), open: Number(row.open), high: Number(row.high), low: Number(row.low), close: Number(row.close) };
    if ([candle.time, candle.open, candle.high, candle.low, candle.close].every((value) => Number.isFinite(value) && value > 0)) out.push(candle);
  }
  out.sort((a, b) => a.time - b.time);
  return out.filter((row, index) => index === 0 || row.time !== out[index - 1].time);
}

function axisTime(timeframe: string) {
  return (time: unknown) => {
    const seconds = typeof time === "number" ? time : 0;
    if (!seconds) return "";
    const date = new Date(seconds * 1000);
    if (timeframe === "24u") return date.toLocaleDateString("nl-NL", { timeZone: "Europe/Amsterdam", day: "2-digit", month: "short" });
    if (timeframe === "4u" || timeframe === "1u") return date.toLocaleString("nl-NL", { timeZone: "Europe/Amsterdam", day: "2-digit", month: "short", hour: "2-digit", hourCycle: "h23" });
    return date.toLocaleTimeString("nl-NL", { timeZone: "Europe/Amsterdam", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  };
}

function CoinKoersCard({ row, onRequestClose }: { row: MarketRow; onRequestClose: () => void }) {
  const [timeframe, setTimeframe] = useState<Timeframe>(() => {
    try { const saved = window.localStorage.getItem(TIMEFRAME_KEY); if (saved && (PORTFOLIO_KOERS_TIMEFRAMES as readonly string[]).includes(saved)) return saved as Timeframe; } catch { /* storage unavailable */ }
    return "15m";
  });
  const [candles, setCandles] = useState<Candle[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [live, setLive] = useState(false);
  const [events, setEvents] = useState<unknown[]>([]);
  const [awayFromNow, setAwayFromNow] = useState(false);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const goToNowRef = useRef<() => void>(() => {});
  const lastTapRef = useRef<{ at: number; x: number; y: number } | null>(null);
  const pressRef = useRef<{ at: number; x: number; y: number; moved: boolean } | null>(null);

  useEffect(() => { try { window.localStorage.setItem(TIMEFRAME_KEY, timeframe); } catch { /* storage unavailable */ } }, [timeframe]);

  // Candles: full history once per timeframe, then the last two candles every few seconds.
  useEffect(() => {
    let cancelled = false;
    const interval = INTERVAL[timeframe] || "15m";
    const base = `/api/market-data?exchange=aster&market=${encodeURIComponent(row.symbol)}&interval=${interval}`;
    setStatus("loading"); setCandles([]);
    fetch(`${base}&limit=500`, { cache: "no-store" }).then((response) => response.json()).then((payload) => {
      if (cancelled) return;
      const rows = parseCandles(payload);
      setCandles(rows); setStatus(rows.length ? "ready" : "error"); setLive(rows.length > 0);
    }).catch(() => { if (!cancelled) { setStatus("error"); setLive(false); } });
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      fetch(`${base}&limit=2`, { cache: "no-store" }).then((response) => response.json()).then((payload) => {
        if (cancelled) return;
        const fresh = parseCandles(payload);
        if (!fresh.length) return;
        setLive(true);
        setCandles((current) => {
          if (!current.length) return current;
          const next = current.slice();
          for (const candle of fresh) {
            const last = next[next.length - 1];
            if (candle.time === last.time) next[next.length - 1] = candle;
            else if (candle.time > last.time) next.push(candle);
          }
          return next;
        });
      }).catch(() => { if (!cancelled) setLive(false); });
    }, 5_000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [row.symbol, timeframe]);

  // Your own fills on this market (both legs, all cycles): entries, exits, take profits.
  useEffect(() => {
    let cancelled = false;
    Promise.allSettled(["LONG", "SHORT"].map((side) => authenticatedRequest(`/api/exchanges/aster/trade-events?symbol=${encodeURIComponent(row.symbol)}&side=${side}&all_cycles=true`)))
      .then((results) => {
        if (cancelled) return;
        setEvents(results.flatMap((result) => result.status === "fulfilled" && Array.isArray((result.value as { events?: unknown[] })?.events) ? (result.value as { events: unknown[] }).events : []));
      });
    return () => { cancelled = true; };
  }, [row.symbol]);

  // Build the chart when the timeframe's history arrives.
  const historyKey = status === "ready" ? `${timeframe}:${candles[0]?.time ?? 0}` : "";
  useEffect(() => {
    const container = canvasRef.current;
    if (!container || !historyKey) return;
    const rows = candles;
    const view = VIEW[timeframe] || VIEW["15m"];
    const precision = Math.max(0, Math.min(10, row.pricePrecision ?? 2));
    const chart = createChart(container, {
      width: Math.max(1, container.clientWidth), height: Math.max(220, container.clientHeight),
      layout: { background: { type: ColorType.Solid, color: "#000000" }, textColor: "#aeb6bb", fontSize: 10, attributionLogo: false } as never,
      grid: { vertLines: { color: "rgba(255,255,255,.028)" }, horzLines: { color: "rgba(255,255,255,.04)" } },
      crosshair: { mode: CrosshairMode.MagnetOHLC, vertLine: { color: "rgba(210,220,225,.34)", labelBackgroundColor: "#202326" }, horzLine: { color: "rgba(210,220,225,.34)", labelBackgroundColor: "#202326" } },
      rightPriceScale: { borderColor: "rgba(255,255,255,.14)", minimumWidth: 48, scaleMargins: { top: 0.06, bottom: 0.06 } },
      timeScale: { borderColor: "rgba(255,255,255,.14)", timeVisible: true, secondsVisible: false, rightOffset: view.rightOffset, barSpacing: view.barSpacing, minBarSpacing: 3, tickMarkFormatter: axisTime(timeframe) },
      localization: { locale: "nl-NL", priceFormatter: (price: number) => formatMarketPrice(price, precision) },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
      // Double tap belongs to the flip, so the axis double-click reset stays off here.
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true, axisDoubleClickReset: false },
      trackingMode: { exitMode: TrackingModeExitMode.OnTouchEnd },
      kineticScroll: { touch: true, mouse: false },
    });
    chartRef.current = chart;
    const series = chart.addSeries(CandlestickSeries, { upColor: "#17e6a0", downColor: "#ff5a66", wickUpColor: "#17e6a0", wickDownColor: "#ff6a74", borderVisible: false, priceLineVisible: true, priceLineColor: "#e4b84a", priceLineStyle: 2, lastValueVisible: true, priceFormat: { type: "price", precision, minMove: 1 / 10 ** precision } });
    seriesRef.current = series;
    series.setData(rows.map((candle) => ({ ...candle, time: candle.time as UTCTimestamp })));
    const bb = bollinger20x2(rows);
    const band = (color: string, width: number, style = 0) => chart.addSeries(LineSeries, { color, lineWidth: width as 1 | 2, lineStyle: style, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    const upper = band("rgba(35,190,255,.82)", 2), middle = band("rgba(218,231,236,.44)", 1, 2), lower = band("rgba(35,190,255,.82)", 2);
    upper.setData(bb.upper.map((point: { time: number; value: number }) => ({ time: point.time as UTCTimestamp, value: point.value })));
    middle.setData(bb.middle.map((point: { time: number; value: number }) => ({ time: point.time as UTCTimestamp, value: point.value })));
    lower.setData(bb.lower.map((point: { time: number; value: number }) => ({ time: point.time as UTCTimestamp, value: point.value })));
    const markers = createSeriesMarkers(series, []);
    (chart as unknown as { __tmMarkers?: typeof markers }).__tmMarkers = markers;

    const timeScale = chart.timeScale();
    const priceScale = chart.priceScale("right");
    const latestTo = rows.length - 1 + view.rightOffset;
    timeScale.setVisibleLogicalRange({ from: rows.length - view.visibleBars - 0.5, to: latestTo });
    const updateAway = () => {
      const range = timeScale.getVisibleLogicalRange();
      const current = (seriesRef.current?.data().length ?? rows.length) - 1;
      setAwayFromNow(Boolean(range && Number(range.to) < current - 0.5) || priceScale.options().autoScale === false);
    };
    timeScale.subscribeVisibleLogicalRangeChange(updateAway);
    goToNowRef.current = () => {
      const count = seriesRef.current?.data().length ?? rows.length;
      try { priceScale.setAutoScale(true); timeScale.setVisibleLogicalRange({ from: count - view.visibleBars - 0.5, to: count - 1 + view.rightOffset }); } catch { /* disposed */ }
      setAwayFromNow(false);
    };

    // Build 637 behaviour: up/down drags move the price range right away.
    let gesture: { id: number; x: number; y: number; frozen: boolean; decided: boolean } | null = null;
    const onGestureDown = (event: PointerEvent) => {
      if (!event.isPrimary || (event.pointerType === "mouse" && event.button !== 0)) return;
      let frozen = false;
      try {
        if (priceScale.options().autoScale !== false) {
          const range = priceScale.getVisibleRange();
          if (range && Number(range.to) > Number(range.from)) { priceScale.setAutoScale(false); priceScale.setVisibleRange({ from: Number(range.from), to: Number(range.to) }); frozen = true; }
        }
      } catch { /* disposed */ }
      gesture = { id: event.pointerId, x: event.clientX, y: event.clientY, frozen, decided: !frozen };
    };
    const onGestureMove = (event: PointerEvent) => {
      if (!gesture || event.pointerId !== gesture.id || gesture.decided) return;
      const dx = event.clientX - gesture.x, dy = event.clientY - gesture.y;
      if (Math.hypot(dx, dy) < 10) return;
      gesture.decided = true;
      if (gesture.frozen && Math.abs(dx) > 2.5 * Math.abs(dy)) { try { priceScale.setAutoScale(true); } catch { /* disposed */ } }
    };
    const onGestureEnd = (event: PointerEvent) => {
      if (!gesture || event.pointerId !== gesture.id) return;
      if (gesture.frozen && !gesture.decided) { try { priceScale.setAutoScale(true); } catch { /* disposed */ } }
      gesture = null; updateAway();
    };
    const onSecondFinger = (event: TouchEvent) => {
      if (event.touches.length > 1 && gesture && gesture.frozen && !gesture.decided) { gesture.decided = true; try { priceScale.setAutoScale(true); } catch { /* disposed */ } }
    };
    container.addEventListener("pointerdown", onGestureDown, { capture: true, passive: true });
    container.addEventListener("pointermove", onGestureMove, { capture: true, passive: true });
    container.addEventListener("touchstart", onSecondFinger, { capture: true, passive: true });
    window.addEventListener("pointerup", onGestureEnd, { passive: true });
    window.addEventListener("pointercancel", onGestureEnd, { passive: true });

    const resize = new ResizeObserver(() => {
      if (chartRef.current !== chart || !container.isConnected) return;
      try { chart.applyOptions({ width: Math.max(1, container.clientWidth), height: Math.max(220, container.clientHeight) }); } catch { /* disposed */ }
    });
    resize.observe(container);
    return () => {
      resize.disconnect();
      container.removeEventListener("pointerdown", onGestureDown, { capture: true });
      container.removeEventListener("pointermove", onGestureMove, { capture: true });
      container.removeEventListener("touchstart", onSecondFinger, { capture: true });
      window.removeEventListener("pointerup", onGestureEnd); window.removeEventListener("pointercancel", onGestureEnd);
      try { timeScale.unsubscribeVisibleLogicalRangeChange(updateAway); chart.remove(); } catch { /* disposed */ }
      if (chartRef.current === chart) { chartRef.current = null; seriesRef.current = null; }
    };
    // Rebuild only when a new history arrives; live ticks are applied below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historyKey]);

  // Live ticks: update the last candle without rebuilding the chart.
  useEffect(() => {
    const series = seriesRef.current;
    const last = candles[candles.length - 1];
    if (!series || !last) return;
    try {
      const shown = series.data();
      const lastShown = shown[shown.length - 1] as { time?: number } | undefined;
      if (lastShown && Number(lastShown.time) <= last.time) series.update({ ...last, time: last.time as UTCTimestamp });
    } catch { /* disposed */ }
  }, [candles]);

  // Trade labels follow the candles they belong to.
  useEffect(() => {
    const chart = chartRef.current as unknown as { __tmMarkers?: { setMarkers: (markers: unknown[]) => void } } | null;
    if (!chart?.__tmMarkers || !candles.length) return;
    const markers = tradeMarkersFromEvents(events, candles.map((candle) => candle.time));
    try { chart.__tmMarkers.setMarkers(markers.map((marker) => ({ time: marker.time as UTCTimestamp, position: marker.position, shape: marker.shape, color: marker.color, text: marker.text, size: marker.kind === "tp" ? 1.2 : 1 }))); } catch { /* disposed */ }
  }, [events, candles, historyKey]);

  // Double tap anywhere on the card flips it back (taps only, never after a drag).
  const onPointerDown = useCallback((event: ReactPointerEvent) => {
    pressRef.current = { at: Date.now(), x: event.clientX, y: event.clientY, moved: false };
  }, []);
  const onPointerMove = useCallback((event: ReactPointerEvent) => {
    const press = pressRef.current;
    if (press && Math.hypot(event.clientX - press.x, event.clientY - press.y) > 10) press.moved = true;
  }, []);
  const onPointerUp = useCallback((event: ReactPointerEvent) => {
    const press = pressRef.current;
    pressRef.current = null;
    if (!press || press.moved || Date.now() - press.at > 260) { lastTapRef.current = null; return; }
    if ((event.target as HTMLElement | null)?.closest("button")) return;
    const last = lastTapRef.current;
    const now = Date.now();
    if (last && now - last.at < DOUBLE_TAP_MS && Math.hypot(event.clientX - last.x, event.clientY - last.y) < 40) {
      lastTapRef.current = null;
      onRequestClose();
      return;
    }
    lastTapRef.current = { at: now, x: event.clientX, y: event.clientY };
  }, [onRequestClose]);

  const lastClose = candles[candles.length - 1]?.close ?? row.lastPrice;
  const precision = row.pricePrecision ?? 2;
  const change = row.change24hPct;
  const high = Math.max(row.high24h || 0, lastClose);
  const low = row.low24h > 0 ? Math.min(row.low24h, lastClose) : lastClose;

  return <section className={`portfolio-koers-card portfolio-koers-ui41 ${styles.koers}`} aria-label={`${row.baseAsset} Koers`}
    onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onDoubleClick={onRequestClose}>
    <header className="portfolio-koers-header portfolio-koers-ui41-header">
      <div className="portfolio-koers-ui41-top">
        <div className="portfolio-koers-heading">
          <div className="portfolio-koers-title-line"><h2>{row.baseAsset} Koers</h2><span className={live ? "portfolio-koers-live is-live" : "portfolio-koers-live"}><i />{live ? "Live" : "Sync"}</span></div>
          <small>{row.name ? `${row.name} · ` : ""}{row.symbol} · Perpetual</small>
        </div>
        <div className="portfolio-koers-ui41-actions">
          <button type="button" className={`portfolio-koers-settings ${styles.close}`} onClick={onRequestClose} aria-label="Terugdraaien naar Markets">✕</button>
        </div>
      </div>
      <div className="portfolio-koers-ui41-metrics">
        <div className="portfolio-koers-ui41-value">
          <strong>{formatMarketPrice(lastClose, precision)}</strong>
          <span className={change < 0 ? "negative" : ""}>{signedPercent(change)}</span>
        </div>
        <div className="portfolio-koers-day-range" aria-label="High en low 24 uur">
          <article className="high"><small>High 24u</small><strong>{formatMarketPrice(high, precision)}</strong></article>
          <article className="low"><small>Low 24u</small><strong>{formatMarketPrice(low, precision)}</strong></article>
        </div>
      </div>
      <div className="portfolio-koers-ui41-controls">
        <div className="portfolio-koers-toolbar" role="group" aria-label={`${row.baseAsset} Koers timeframe`}>
          {PORTFOLIO_KOERS_TIMEFRAMES.map((value) => <button type="button" key={value} className={timeframe === value ? "active" : ""} onClick={() => setTimeframe(value as Timeframe)}>{value}</button>)}
        </div>
      </div>
    </header>
    <div className={`portfolio-koers-stage ${styles.stage}`}>
      <div ref={canvasRef} className="portfolio-koers-canvas" />
      {status === "loading" ? <div className="portfolio-koers-state portfolio-koers-initial-state"><i />Koers laden…</div> : null}
      {status === "error" ? <div className="portfolio-koers-state portfolio-koers-initial-state">Koers tijdelijk niet beschikbaar</div> : null}
      <button type="button" className={`portfolio-koers-now ${awayFromNow ? "is-visible" : ""}`} onClick={() => goToNowRef.current()} tabIndex={awayFromNow ? 0 : -1} aria-hidden={!awayFromNow} aria-label="Terug naar de actuele koers"><span aria-hidden="true">⟶</span>Nu</button>
    </div>
  </section>;
}

export function MarketsCoinFlip({ row, originRect, onClosed }: { row: MarketRow; originRect: DOMRect; onClosed: () => void }) {
  const cardRef = useRef<HTMLDivElement | null>(null);
  const backdropRef = useRef<HTMLDivElement | null>(null);
  const [mounted, setMounted] = useState(false);
  // opening: 3D flip from the row to full screen · open: flat full-screen chart · closing: flip back.
  const [phase, setPhase] = useState<"opening" | "open" | "closing">("opening");
  const phaseRef = useRef(phase);
  phaseRef.current = phase;
  const reduced = typeof window !== "undefined" && Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

  useEffect(() => { setMounted(true); }, []);

  // Lock the page underneath while the chart is open.
  useEffect(() => {
    const html = document.documentElement;
    const previous = html.style.overflow;
    html.style.overflow = "hidden";
    return () => { html.style.overflow = previous; };
  }, []);

  const rowRect = useCallback(() => {
    const live = document.querySelector<HTMLElement>(`[data-market-symbol="${CSS.escape(row.symbol)}"]`);
    const rect = live?.getBoundingClientRect();
    return rect && rect.width > 0 && rect.bottom > 0 && rect.top < window.innerHeight ? rect : originRect;
  }, [originRect, row.symbol]);

  const keyframes = useCallback((rect: DOMRect): Keyframe[] => {
    const scaleX = rect.width / Math.max(1, window.innerWidth), scaleY = rect.height / Math.max(1, window.innerHeight);
    return [
      { transform: `translate(${rect.left}px, ${rect.top}px) scale(${scaleX}, ${scaleY}) rotateY(0deg)`, borderRadius: "14px" },
      { transform: "translate(0px, 0px) scale(1, 1) rotateY(180deg)", borderRadius: "0px" },
    ];
  }, []);

  useLayoutEffect(() => {
    if (!mounted) return;
    const card = cardRef.current, backdrop = backdropRef.current;
    if (!card || !backdrop || reduced) { setPhase("open"); return; }
    const animation = card.animate(keyframes(rowRect()), { duration: FLIP_MS, easing: "cubic-bezier(.2,.75,.15,1)", fill: "forwards" });
    backdrop.animate([{ opacity: 0 }, { opacity: 1 }], { duration: FLIP_MS * 0.6, easing: "ease-out", fill: "forwards" });
    animation.onfinish = () => { if (phaseRef.current === "opening") { animation.cancel(); setPhase("open"); } };
    return () => { animation.onfinish = null; };
  }, [mounted, reduced, keyframes, rowRect]);

  const close = useCallback(() => {
    if (phaseRef.current === "closing") return;
    setPhase("closing");
    const card = cardRef.current, backdrop = backdropRef.current;
    if (!card || !backdrop || reduced) { onClosed(); return; }
    const frames = keyframes(rowRect());
    const animation = card.animate([frames[1], frames[0]], { duration: FLIP_MS, easing: "cubic-bezier(.45,0,.2,1)", fill: "forwards" });
    backdrop.animate([{ opacity: 1 }, { opacity: 0 }], { duration: FLIP_MS, easing: "ease-in", fill: "forwards" });
    animation.onfinish = () => onClosed();
    animation.oncancel = () => onClosed();
  }, [keyframes, onClosed, reduced, rowRect]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  if (!mounted) return null;
  const up = row.change24hPct > 0, down = row.change24hPct < 0;
  return createPortal(<div className={styles.overlay} role="dialog" aria-modal="true" aria-label={`${row.baseAsset} Koers`}>
    <div ref={backdropRef} className={styles.backdrop} />
    <div className={styles.stageWrap}>
      <div ref={cardRef} className={`${styles.card} ${phase === "open" ? styles.cardOpen : styles.cardFlipping}`}>
        <div className={`${styles.front} ${up ? styles.frontUp : down ? styles.frontDown : ""}`} aria-hidden="true" />
        <div className={styles.back}>
          <CoinKoersCard row={row} onRequestClose={close} />
        </div>
      </div>
    </div>
  </div>, document.body);
}
