"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { dominancePresentation, positionExposure } from "@/lib/portfolio-impact-battle.mjs";
import styles from "./portfolio-impact-battle.module.css";

type BattlePosition = Record<string, unknown>;
type Timeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "24h";
type PressureComponents = { price: number; candles: number; momentum: number; trend: number; breadth: number };
type MarketPressurePayload = {
  timeframe: Timeframe;
  score: number;
  longShare: number;
  shortShare: number;
  stateIndex: number;
  status: string;
  barLabel: string;
  symbolsUsed: string[];
  updatedAt: number;
  breadth?: { up: number; down: number; flat: number };
  components?: PressureComponents;
};

type Props = {
  positions: unknown[];
  equity: number | null;
  dataAvailable: boolean;
  updatedAt?: number | null;
  marketPressureOverride?: Partial<Record<Timeframe, number>>;
};

const TIMEFRAMES: Array<{ id: Timeframe; label: string }> = [
  { id: "1m", label: "1m" },
  { id: "5m", label: "5m" },
  { id: "15m", label: "15m" },
  { id: "1h", label: "1u" },
  { id: "4h", label: "4u" },
  { id: "24h", label: "24u" },
];
const REFRESH_MS: Record<Timeframe, number> = {
  "1m": 15_000,
  "5m": 25_000,
  "15m": 40_000,
  "1h": 60_000,
  "4h": 120_000,
  "24h": 300_000,
};
const money = new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const percent = new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function numberFrom(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function positionSide(position: unknown) {
  if (!position || typeof position !== "object") return "";
  return String((position as BattlePosition).side ?? "").toLowerCase();
}

function positionSymbol(position: unknown) {
  if (!position || typeof position !== "object") return "";
  return String((position as BattlePosition).symbol ?? "").toUpperCase().replace(/[\/_-]/g, "");
}

function positionPnl(position: unknown) {
  if (!position || typeof position !== "object") return 0;
  const record = position as BattlePosition;
  return numberFrom(record.pnl ?? record.openPnl ?? record.unrealizedPnl ?? record.unrealizedProfit);
}

function formatUsd(value: number, signed = false) {
  if (!Number.isFinite(value)) return "—";
  const normalized = Math.abs(value) < 0.005 ? 0 : value;
  const sign = signed && normalized > 0 ? "+" : normalized < 0 ? "-" : "";
  return `$${sign}${money.format(Math.abs(normalized))}`;
}

function formatPercent(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "—";
  const normalized = Math.abs(value) < 0.005 ? 0 : value;
  const sign = normalized > 0 ? "+" : normalized < 0 ? "-" : "";
  return `${sign}${percent.format(Math.abs(normalized))}%`;
}

function tone(value: number) {
  return value > 0.005 ? styles.positive : value < -0.005 ? styles.negative : styles.neutral;
}

function scenePath(index: number) {
  return `/portfolio-impact-states/state-${String(index).padStart(2, "0")}.svg`;
}

function asPressure(value: unknown, timeframe: Timeframe): MarketPressurePayload | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const score = Number(row.score);
  if (!Number.isFinite(score)) return null;
  const presentation = dominancePresentation(score);
  const symbolsUsed = Array.isArray(row.symbolsUsed) ? row.symbolsUsed.map(String).filter(Boolean) : [];
  const breadthRow = row.breadth && typeof row.breadth === "object" ? row.breadth as Record<string, unknown> : null;
  const componentsRow = row.components && typeof row.components === "object" ? row.components as Record<string, unknown> : null;
  return {
    timeframe,
    score: presentation.score,
    longShare: presentation.longShare,
    shortShare: presentation.shortShare,
    stateIndex: presentation.stateIndex,
    status: presentation.status,
    barLabel: presentation.barLabel,
    symbolsUsed,
    updatedAt: Number.isFinite(Number(row.updatedAt)) ? Number(row.updatedAt) : Date.now(),
    breadth: breadthRow ? { up: numberFrom(breadthRow.up), down: numberFrom(breadthRow.down), flat: numberFrom(breadthRow.flat) } : undefined,
    components: componentsRow ? {
      price: numberFrom(componentsRow.price),
      candles: numberFrom(componentsRow.candles),
      momentum: numberFrom(componentsRow.momentum),
      trend: numberFrom(componentsRow.trend),
      breadth: numberFrom(componentsRow.breadth),
    } : undefined,
  };
}

export function PortfolioImpactBattle({ positions, equity, dataAvailable, updatedAt, marketPressureOverride }: Props) {
  const [timeframe, setTimeframe] = useState<Timeframe>("15m");
  const [pressure, setPressure] = useState<MarketPressurePayload | null>(null);
  const [loadingPressure, setLoadingPressure] = useState(true);
  const [pressureError, setPressureError] = useState("");
  const [visualStateIndex, setVisualStateIndex] = useState(8);
  const visualStateRef = useRef(8);
  const pendingStateTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pressureCache = useRef(new Map<string, MarketPressurePayload>());

  const snapshot = useMemo(() => {
    const longs = positions.filter((position) => positionSide(position) === "long");
    const shorts = positions.filter((position) => positionSide(position) === "short");
    const longPnl = longs.reduce((total, position) => total + positionPnl(position), 0);
    const shortPnl = shorts.reduce((total, position) => total + positionPnl(position), 0);
    return { longs, shorts, longPnl, shortPnl };
  }, [positions]);

  const marketSymbols = useMemo(() => {
    const exposureBySymbol = new Map<string, number>();
    for (const position of positions) {
      const symbol = positionSymbol(position);
      if (!/^[A-Z0-9]+USDT$/.test(symbol)) continue;
      exposureBySymbol.set(symbol, (exposureBySymbol.get(symbol) ?? 0) + positionExposure(position));
    }
    return Array.from(exposureBySymbol.entries())
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, 16)
      .map(([symbol]) => symbol);
  }, [positions]);
  const symbolKey = marketSymbols.join(",");

  useEffect(() => {
    const images = Array.from({ length: 17 }, (_, index) => {
      const image = new Image();
      image.decoding = "async";
      image.src = scenePath(index);
      return image;
    });
    return () => { images.forEach((image) => { image.src = ""; }); };
  }, []);

  useEffect(() => {
    let active = true;
    const cacheKey = `${timeframe}|${symbolKey}`;
    const setStateSafely = (target: number, immediate = false) => {
      const next = Math.min(16, Math.max(0, Math.round(target)));
      if (pendingStateTimer.current) {
        clearTimeout(pendingStateTimer.current);
        pendingStateTimer.current = null;
      }
      if (immediate || Math.abs(next - visualStateRef.current) >= 2) {
        visualStateRef.current = next;
        setVisualStateIndex(next);
        return;
      }
      if (next === visualStateRef.current) return;
      pendingStateTimer.current = setTimeout(() => {
        if (!active) return;
        visualStateRef.current = next;
        setVisualStateIndex(next);
      }, 650);
    };

    const overrideScore = marketPressureOverride?.[timeframe];
    if (Number.isFinite(Number(overrideScore))) {
      const presentation = dominancePresentation(Number(overrideScore));
      const next: MarketPressurePayload = {
        timeframe,
        score: presentation.score,
        longShare: presentation.longShare,
        shortShare: presentation.shortShare,
        stateIndex: presentation.stateIndex,
        status: presentation.status,
        barLabel: presentation.barLabel,
        symbolsUsed: marketSymbols.length ? marketSymbols : ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        updatedAt: Date.now(),
      };
      setPressure(next);
      setLoadingPressure(false);
      setPressureError("");
      setStateSafely(next.stateIndex, true);
      return () => { active = false; };
    }

    const cached = pressureCache.current.get(cacheKey);
    if (cached) {
      setPressure(cached);
      setLoadingPressure(false);
      setPressureError("");
      setStateSafely(cached.stateIndex, true);
    } else {
      setPressure(null);
      setLoadingPressure(true);
      setPressureError("");
      setStateSafely(8, true);
    }

    const load = async (quiet = false) => {
      if (!quiet && !pressureCache.current.has(cacheKey)) setLoadingPressure(true);
      try {
        const query = new URLSearchParams({ timeframe });
        if (marketSymbols.length) query.set("symbols", marketSymbols.join(","));
        const response = await authenticatedRequest(`/api/markets/aster/pressure?${query.toString()}`);
        const next = asPressure(response, timeframe);
        if (!next || !active) return;
        pressureCache.current.set(cacheKey, next);
        setPressure(next);
        setPressureError("");
        setLoadingPressure(false);
        setStateSafely(next.stateIndex);
      } catch (reason) {
        if (!active) return;
        setLoadingPressure(false);
        setPressureError(reason instanceof Error ? reason.message : "Marktdruk tijdelijk niet beschikbaar");
      }
    };

    void load(Boolean(cached));
    const interval = window.setInterval(() => { void load(true); }, REFRESH_MS[timeframe]);
    return () => {
      active = false;
      window.clearInterval(interval);
      if (pendingStateTimer.current) {
        clearTimeout(pendingStateTimer.current);
        pendingStateTimer.current = null;
      }
    };
  }, [timeframe, symbolKey, marketPressureOverride]);

  const netPnl = snapshot.longPnl + snapshot.shortPnl;
  const equityBasis = equity && Math.abs(equity) > 0.01 ? Math.abs(equity) : 0;
  const netPercent = equityBasis ? netPnl / equityBasis * 100 : null;
  const longPercent = equityBasis ? snapshot.longPnl / equityBasis * 100 : null;
  const shortPercent = equityBasis ? snapshot.shortPnl / equityBasis * 100 : null;
  const currentPressure = pressure ?? { ...dominancePresentation(0), timeframe, symbolsUsed: [], updatedAt: 0 };
  const scoreLabel = currentPressure.score > 0 ? `+${currentPressure.score}` : String(currentPressure.score);
  const pressureStatus = loadingPressure && !pressure ? "MARKTDRUK WORDT BEREKEND" : pressure?.status ?? "IN EVENWICHT";
  const pressureCaption = pressure
    ? `${pressure.barLabel} · ${TIMEFRAMES.find((item) => item.id === timeframe)?.label} · SCORE ${scoreLabel}${pressure.symbolsUsed.length ? ` · ${pressure.symbolsUsed.length} MARKTEN` : ""}`
    : pressureError ? "MARKTDRUK TIJDELIJK ONBESCHIKBAAR" : "MARKTDRUK";
  const visualStyle = { "--long-share": `${currentPressure.longShare}%` } as React.CSSProperties;

  return <div className={styles.module}>
    <div className={styles.timeframes} role="group" aria-label="Marktdruk timeframe">
      {TIMEFRAMES.map((item) => <button
        key={item.id}
        type="button"
        className={item.id === timeframe ? styles.activeTimeframe : ""}
        aria-pressed={item.id === timeframe}
        onClick={() => setTimeframe(item.id)}
      >{item.label}</button>)}
    </div>

    <section
      className={`${styles.card} ${!dataAvailable ? styles.unavailable : ""}`}
      style={visualStyle}
      data-state-index={visualStateIndex}
      data-timeframe={timeframe}
      data-score={currentPressure.score}
      aria-label={`Portfolio impact. Long open P&L ${formatUsd(snapshot.longPnl, true)}, short open P&L ${formatUsd(snapshot.shortPnl, true)}, netto ${formatUsd(netPnl, true)}. Marktdruk ${pressureStatus}.`}
    >
      <img className={styles.scene} src={scenePath(visualStateIndex)} alt="" aria-hidden="true" />
      <div className={styles.vignette} aria-hidden="true" />
      <div className={styles.impact} aria-hidden="true"><i /><i /><i /></div>

      {!dataAvailable ? <div className={styles.loadingCopy}>
        <span>PORTFOLIO IMPACT</span>
        <strong>Exchangegegevens laden…</strong>
        <small>Marktdruk blijft read-only en opent of sluit nooit posities.</small>
      </div> : <>
        <div className={`${styles.sidePanel} ${styles.longPanel}`}>
          <div className={styles.sideTitle}><span>LONGS</span><i>↗</i></div>
          <small>Open P&amp;L</small>
          <strong className={tone(snapshot.longPnl)}>{formatUsd(snapshot.longPnl, true)}</strong>
          <em className={tone(snapshot.longPnl)}>{formatPercent(longPercent)}</em>
          <span className={styles.positionCount}>{snapshot.longs.length} posities</span>
        </div>

        <div className={styles.centerPanel}>
          <div className={styles.centerTitle}><i />PORTFOLIO IMPACT</div>
          <strong className={tone(netPnl)}>{formatUsd(netPnl, true)}</strong>
          <span className={tone(netPnl)}>{formatPercent(netPercent)}</span>
        </div>

        <div className={`${styles.sidePanel} ${styles.shortPanel}`}>
          <div className={styles.sideTitle}><i>↘</i><span>SHORTS</span></div>
          <small>Open P&amp;L</small>
          <strong className={tone(snapshot.shortPnl)}>{formatUsd(snapshot.shortPnl, true)}</strong>
          <em className={tone(snapshot.shortPnl)}>{formatPercent(shortPercent)}</em>
          <span className={styles.positionCount}>{snapshot.shorts.length} posities</span>
        </div>
      </>}

      <div className={styles.battleFooter}>
        <div className={styles.status}>{pressureStatus}</div>
        <div className={styles.balanceRow}>
          <div className={`${styles.share} ${styles.longShare}`}><strong>{currentPressure.longShare}%</strong></div>
          <div className={styles.balanceTrack} aria-hidden="true"><div className={styles.longFill} /><div className={styles.shortFill} /><i /></div>
          <div className={`${styles.share} ${styles.shortShare}`}><strong>{currentPressure.shortShare}%</strong></div>
        </div>
        <div className={styles.barCaption}>{pressureCaption}</div>
      </div>
    </section>
  </div>;
}
