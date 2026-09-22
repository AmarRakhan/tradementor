"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { authenticatedRequest } from "@/lib/cloud-client";
import {
  PORTFOLIO_TIMEFRAMES,
  apiPortfolioTimeframe,
  buildPortfolioBollingerMarkers,
  buildPortfolioTradeMarkers,
  formatPortfolioUsd,
  mergePortfolioMarkers,
  type PortfolioBollingerPoint,
  type PortfolioEquityCandle,
  type PortfolioEquityChartResponse,
  type PortfolioTimeframe,
  type PortfolioZone,
  type RecentTradeActivity,
} from "@/lib/portfolio-equity-chart";

type Props = {
  activity?: RecentTradeActivity | null;
  refreshKey?: unknown;
};

type ZoneRect = PortfolioZone & { top: number; height: number; center: number };

type TooltipState = {
  x: number;
  y: number;
  atMs: number;
  candle: PortfolioEquityCandle;
  band?: PortfolioBollingerPoint;
  zone?: PortfolioZone;
};

const AMSTERDAM = "Europe/Amsterdam";
const moneyCompact = new Intl.NumberFormat("nl-NL", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
const dateTime = new Intl.DateTimeFormat("nl-NL", {
  timeZone: AMSTERDAM,
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

function chartTimeLabel(time: number) {
  return dateTime.format(new Date(time * 1000));
}

function zoneClass(index: number, active: boolean) {
  if (active) return "active";
  if (index > 0) return index >= 2 ? "upper-strong" : "upper";
  if (index < 0) return index <= -2 ? "lower-strong" : "lower";
  return "anchor";
}

function candleData(rows: PortfolioEquityCandle[]) {
  return rows.map((row) => ({
    time: Math.floor(row.timeMs / 1000) as UTCTimestamp,
    open: row.open,
    high: row.high,
    low: row.low,
    close: row.close,
  }));
}

function lineData(rows: PortfolioBollingerPoint[], key: "upper" | "middle" | "lower") {
  return rows.map((row) => ({
    time: Math.floor(row.timeMs / 1000) as UTCTimestamp,
    value: row[key],
  }));
}

export function AsterPortfolioEquityChart({ activity, refreshKey }: Props) {
  const [timeframe, setTimeframe] = useState<PortfolioTimeframe>("15m");
  const [payload, setPayload] = useState<PortfolioEquityChartResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [fullscreen, setFullscreen] = useState(false);
  const [zoneRects, setZoneRects] = useState<ZoneRect[]>([]);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  const shellRef = useRef<HTMLDivElement | null>(null);
  const chartHostRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const upperRef = useRef<ISeriesApi<"Line"> | null>(null);
  const middleRef = useRef<ISeriesApi<"Line"> | null>(null);
  const lowerRef = useRef<ISeriesApi<"Line"> | null>(null);
  const markerApiRef = useRef<any>(null);
  const payloadRef = useRef<PortfolioEquityChartResponse | null>(null);
  const firstFitRef = useRef(true);
  const zoneFrameRef = useRef<number | null>(null);
  const tapRef = useRef<{ at: number; x: number; y: number } | null>(null);

  const refresh = useCallback(async () => {
    try {
      const interval = apiPortfolioTimeframe(timeframe);
      const next = await authenticatedRequest(
        `/api/exchanges/aster/portfolio-equity?timeframe=${encodeURIComponent(interval)}&limit=180`,
        { cache: "no-store" },
      ) as PortfolioEquityChartResponse;
      if (!next?.reliable || !Array.isArray(next.candles)) throw new Error("Portfolio-koers tijdelijk niet betrouwbaar beschikbaar");
      payloadRef.current = next;
      setPayload(next);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Portfolio-koers kon niet worden geladen");
    } finally {
      setLoading(false);
    }
  }, [timeframe]);

  useEffect(() => {
    setLoading(true);
    firstFitRef.current = true;
    void refresh();
    const timer = window.setInterval(refresh, 10_000);
    const visible = () => { if (document.visibilityState === "visible") void refresh(); };
    document.addEventListener("visibilitychange", visible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [refresh, refreshKey]);

  const syncZoneRects = useCallback(() => {
    if (zoneFrameRef.current !== null) return;
    zoneFrameRef.current = window.requestAnimationFrame(() => {
      zoneFrameRef.current = null;
      const series = candleRef.current;
      const zones = payloadRef.current?.zones?.zones || [];
      if (!series || !zones.length) {
        setZoneRects([]);
        return;
      }
      const next: ZoneRect[] = [];
      for (const zone of zones) {
        const topRaw = series.priceToCoordinate(zone.upper);
        const bottomRaw = series.priceToCoordinate(zone.lower);
        if (topRaw === null || bottomRaw === null) continue;
        const top = Math.min(topRaw, bottomRaw);
        const bottom = Math.max(topRaw, bottomRaw);
        next.push({ ...zone, top, height: Math.max(1, bottom - top), center: (top + bottom) / 2 });
      }
      setZoneRects(next);
    });
  }, []);

  useEffect(() => {
    const host = chartHostRef.current;
    if (!host) return;
    const chart = createChart(host, {
      width: Math.max(280, host.clientWidth),
      height: Math.max(230, host.clientHeight),
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "rgba(239,236,224,.78)", fontFamily: "var(--font-geist-sans), system-ui, sans-serif" },
      grid: {
        vertLines: { color: "rgba(140,177,166,.075)" },
        horzLines: { color: "rgba(140,177,166,.075)" },
      },
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: { top: 0.08, bottom: 0.08 },
        minimumWidth: 48,
      },
      timeScale: {
        borderVisible: false,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 2.5,
        barSpacing: 8,
        minBarSpacing: 4,
        fixLeftEdge: false,
        fixRightEdge: false,
        tickMarkFormatter: (time) => {
          const date = new Date(Number(time) * 1000);
          return new Intl.DateTimeFormat("nl-NL", { timeZone: AMSTERDAM, day: "2-digit", month: "short" }).format(date);
        },
      },
      localization: { timeFormatter: (time) => chartTimeLabel(Number(time)) },
      crosshair: { mode: CrosshairMode.Normal },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
    });
    const common = { priceLineVisible: false, lastValueVisible: false };
    const candles = chart.addSeries(CandlestickSeries, {
      ...common,
      upColor: "#2ee99a",
      downColor: "#ff5f78",
      wickUpColor: "#4af0aa",
      wickDownColor: "#ff7188",
      borderVisible: false,
      lastValueVisible: true,
      priceLineVisible: true,
      priceLineColor: "#3cf0a0",
      priceLineStyle: 2,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    const upper = chart.addSeries(LineSeries, { ...common, color: "#2a9cff", lineWidth: 1, crosshairMarkerVisible: false });
    const middle = chart.addSeries(LineSeries, { ...common, color: "rgba(240,240,235,.78)", lineWidth: 1, lineStyle: 2, crosshairMarkerVisible: false });
    const lower = chart.addSeries(LineSeries, { ...common, color: "#ff456a", lineWidth: 1, crosshairMarkerVisible: false });

    chartRef.current = chart;
    candleRef.current = candles;
    upperRef.current = upper;
    middleRef.current = middle;
    lowerRef.current = lower;

    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: Math.max(280, host.clientWidth), height: Math.max(230, host.clientHeight) });
      syncZoneRects();
    });
    observer.observe(host);
    const rangeChanged = () => syncZoneRects();
    chart.timeScale().subscribeVisibleLogicalRangeChange(rangeChanged);

    const onCrosshair = (param: any) => {
      if (!param?.time || !param?.point) {
        setTooltip(null);
        return;
      }
      const current = payloadRef.current;
      const atMs = Number(param.time) * 1000;
      const candle = current?.candles.find((row) => row.timeMs === atMs);
      if (!current || !candle) return;
      const band = current.bollinger.find((row) => row.timeMs === atMs);
      const zone = current.zones?.zones?.find((row) => candle.close >= row.lower && candle.close <= row.upper);
      setTooltip({ x: Number(param.point.x), y: Number(param.point.y), atMs, candle, band, zone });
    };
    chart.subscribeCrosshairMove(onCrosshair);
    const pointerSync = () => syncZoneRects();
    host.addEventListener("pointermove", pointerSync);
    host.addEventListener("wheel", pointerSync, { passive: true });
    host.addEventListener("touchmove", pointerSync, { passive: true });

    return () => {
      observer.disconnect();
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(rangeChanged);
      chart.unsubscribeCrosshairMove(onCrosshair);
      host.removeEventListener("pointermove", pointerSync);
      host.removeEventListener("wheel", pointerSync);
      host.removeEventListener("touchmove", pointerSync);
      if (zoneFrameRef.current !== null) cancelAnimationFrame(zoneFrameRef.current);
      markerApiRef.current = null;
      chartRef.current = null;
      candleRef.current = null;
      upperRef.current = null;
      middleRef.current = null;
      lowerRef.current = null;
      try { chart.remove(); } catch { /* navigation already removed chart */ }
    };
  }, [syncZoneRects]);

  const markers = useMemo(() => {
    if (!payload) return [];
    return mergePortfolioMarkers(
      buildPortfolioTradeMarkers(activity, payload.candles, timeframe),
      buildPortfolioBollingerMarkers(payload.bollingerEvents, payload.candles, timeframe),
    );
  }, [activity, payload, timeframe]);

  useEffect(() => {
    const chart = chartRef.current;
    const candles = candleRef.current;
    if (!chart || !candles || !payload) return;
    const data = candleData(payload.candles);
    candles.setData(data);
    upperRef.current?.setData(lineData(payload.bollinger, "upper"));
    middleRef.current?.setData(lineData(payload.bollinger, "middle"));
    lowerRef.current?.setData(lineData(payload.bollinger, "lower"));
    const markerRows = markers.map((marker) => ({
      time: marker.time as UTCTimestamp,
      position: marker.position,
      color: marker.color,
      shape: marker.shape,
      text: marker.text,
      size: marker.size,
    }));
    if (!markerApiRef.current) markerApiRef.current = createSeriesMarkers(candles, markerRows);
    else markerApiRef.current.setMarkers(markerRows);

    if (firstFitRef.current && data.length) {
      firstFitRef.current = false;
      const visible = Math.min(data.length, fullscreen ? 92 : 58);
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, data.length - visible), to: data.length + 2 });
    }
    window.requestAnimationFrame(syncZoneRects);
  }, [payload, markers, fullscreen, syncZoneRects]);

  useEffect(() => {
    if (!fullscreen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setFullscreen(false); };
    window.addEventListener("keydown", escape);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", escape);
    };
  }, [fullscreen]);

  useEffect(() => {
    window.requestAnimationFrame(() => {
      const host = chartHostRef.current;
      const chart = chartRef.current;
      if (!host || !chart) return;
      chart.applyOptions({ width: Math.max(280, host.clientWidth), height: Math.max(230, host.clientHeight) });
      if (payload?.candles.length) {
        const visible = Math.min(payload.candles.length, fullscreen ? 92 : 58);
        chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, payload.candles.length - visible), to: payload.candles.length + 2 });
      }
      syncZoneRects();
    });
  }, [fullscreen, payload, syncZoneRects]);

  const handlePointerUp = (event: React.PointerEvent) => {
    if (event.pointerType !== "touch" && event.pointerType !== "pen") return;
    const now = performance.now();
    const previous = tapRef.current;
    if (previous && now - previous.at <= 360 && Math.hypot(event.clientX - previous.x, event.clientY - previous.y) <= 28) {
      tapRef.current = null;
      setFullscreen((value) => !value);
      return;
    }
    tapRef.current = { at: now, x: event.clientX, y: event.clientY };
  };

  const activeZone = payload?.zones?.activeZone;
  const latest = payload?.candles.at(-1);
  const coverageMessage = payload && payload.candles.length < 20
    ? "Historie wordt vanaf het eerste betrouwbare serverpunt opgebouwd."
    : error;

  return (
    <section
      ref={shellRef}
      className={`aster-portfolio-equity-chart ${fullscreen ? "is-fullscreen" : ""}`}
      aria-label="Portfolio Koers"
      data-reference="file_00000000c7ec820ab9697735bb027326"
      onDoubleClick={() => setFullscreen((value) => !value)}
      onPointerUp={handlePointerUp}
    >
      <header className="apez-head">
        <div className="apez-title">
          <span className="apez-title-glyph" aria-hidden="true">▥</span>
          <div><h2>Portfolio Koers</h2><small>Totale portfolio waarde (USDT)</small></div>
          <span className="apez-live"><i />Live</span>
        </div>
        <div className="apez-timeframes" role="group" aria-label="Portfolio timeframe">
          {PORTFOLIO_TIMEFRAMES.map((value) => (
            <button key={value} type="button" className={timeframe === value ? "active" : ""} onClick={(event) => { event.stopPropagation(); setTimeframe(value); }}>
              {value}
            </button>
          ))}
        </div>
        <button className="apez-fullscreen" type="button" aria-label={fullscreen ? "Verklein Portfolio Koers" : "Portfolio Koers fullscreen"} onClick={(event) => { event.stopPropagation(); setFullscreen((value) => !value); }}>↗</button>
      </header>

      <div className="apez-body">
        <div className="apez-chart-wrap">
          <div className="apez-zone-overlay" aria-hidden="true">
            {zoneRects.map((zone) => <span key={`${zone.label}:${zone.lower}`} className={`apez-zone-band zone-${zoneClass(zone.index, zone.active)}`} style={{ top: zone.top, height: zone.height }} />)}
          </div>
          <div ref={chartHostRef} className="apez-chart-host" />
          {tooltip ? <div className="apez-tooltip" style={{ left: Math.max(8, Math.min(tooltip.x + 10, (chartHostRef.current?.clientWidth || 280) - 174)), top: Math.max(8, tooltip.y - 62) }}>
            <strong>{dateTime.format(new Date(tooltip.atMs))}</strong>
            <span>O {formatPortfolioUsd(tooltip.candle.open)} · H {formatPortfolioUsd(tooltip.candle.high)}</span>
            <span>L {formatPortfolioUsd(tooltip.candle.low)} · C {formatPortfolioUsd(tooltip.candle.close)}</span>
            {tooltip.zone ? <em>{tooltip.zone.label}</em> : null}
            {tooltip.band ? <small>BB {formatPortfolioUsd(tooltip.band.lower)} – {formatPortfolioUsd(tooltip.band.upper)}</small> : null}
          </div> : null}
          {loading && !payload ? <div className="apez-state">Portfolio-koers laden…</div> : null}
          {!loading && !payload && error ? <div className="apez-state error">{error}</div> : null}
          {coverageMessage && payload ? <div className="apez-history-note">{coverageMessage}</div> : null}
        </div>

        <aside className="apez-zone-rail" aria-label="Structurele prijszones">
          {zoneRects.map((zone) => (
            <div
              key={`rail:${zone.label}:${zone.lower}`}
              className={`apez-zone-pill zone-${zoneClass(zone.index, zone.active)}`}
              style={{ top: Math.max(2, zone.center - 20) }}
            >
              <b>{zone.label}</b>
              <span>{Math.round((zone.lower + zone.upper) / 2).toLocaleString("nl-NL")}</span>
            </div>
          ))}
        </aside>
      </div>

      <footer className="apez-footer">
        <span className="apez-current"><i />{latest ? formatPortfolioUsd(latest.close) : "—"}</span>
        <span>{activeZone ? `${activeZone.label} actief` : "Structuur wordt bevestigd"}</span>
        <small>{payload?.cashflowComplete === false ? "Externe cashflowhistorie onvolledig" : "Externe cashflows geneutraliseerd"}</small>
      </footer>
    </section>
  );
}
