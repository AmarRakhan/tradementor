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
const FRAME_COUNT = 201;
const NEUTRAL_FRAME = 100;
const FRAME_INTERVAL_MS = 25;
const BATTLE_LOOP_FRAMES = 50;
const BATTLE_FPS = 20;
const BATTLE_FRAME_MS = Math.round(1000 / BATTLE_FPS);
const BATTLE_SOURCE = "/portfolio-impact-frames/frame-100.svg";
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

function formatShare(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1).replace(".", ",");
}

function tone(value: number) {
  return value > 0.005 ? styles.positive : value < -0.005 ? styles.negative : styles.neutral;
}

function framePath(index: number) {
  const safe = Math.min(FRAME_COUNT - 1, Math.max(0, Math.round(index)));
  return `/portfolio-impact-frames/frame-${String(safe).padStart(3, "0")}.svg`;
}

function shareToFrame(longShare: number) {
  return Math.min(FRAME_COUNT - 1, Math.max(0, Math.round(numberFrom(longShare) * 2)));
}

function frameToShare(index: number) {
  return Math.min(100, Math.max(0, index / 2));
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

function BattleArtwork({ frame, longShare }: { frame: number; longShare: number }) {
  const phase = frame / BATTLE_LOOP_FRAMES * Math.PI * 4;
  const shove = Math.sin(phase);
  const secondary = Math.sin(phase * 2 + 0.35);
  const longLift = Math.max(0, Math.sin(phase));
  const shortLift = Math.max(0, Math.sin(phase + Math.PI));
  const longRear = Math.max(0, Math.sin(phase + Math.PI));
  const shortRear = Math.max(0, Math.sin(phase));
  const battleShift = Math.max(-42, Math.min(42, (longShare - 50) * 1.4));
  const longHeadX = shove * 4.2 + secondary * 0.9;
  const shortHeadX = -shove * 4.2 - secondary * 0.9;
  const longBodyX = shove * 1.7;
  const shortBodyX = -shove * 1.7;
  const longBodyY = Math.sin(phase + 0.25) * 1.4;
  const shortBodyY = Math.sin(phase + Math.PI + 0.25) * 1.4;
  const sparkPulse = 0.72 + (Math.sin(phase * 3) + 1) * 0.12;
  const dust = Array.from({ length: 18 }, (_, index) => {
    const seed = index * 1.618 + frame * 0.21;
    const side = index % 2 === 0 ? -1 : 1;
    const cx = side < 0 ? 250 + Math.sin(seed) * 42 : 470 + Math.sin(seed * 1.17) * 42;
    const cy = 218 + Math.cos(seed * 0.73) * 9 - (frame % 8) * 0.45;
    const opacity = 0.12 + ((index * 17 + frame * 7) % 31) / 100;
    return { cx, cy, opacity, side };
  });
  const sparks = Array.from({ length: 14 }, (_, index) => {
    const angle = index / 14 * Math.PI * 2 + frame * 0.08;
    const radius = 9 + (index % 5) * 5 + (frame % 6);
    return {
      cx: 360 + Math.cos(angle) * radius,
      cy: 139 + Math.sin(angle) * radius * 0.72 - (frame % 5) * 0.35,
      opacity: 0.38 + (index % 4) * 0.11,
    };
  });

  return <svg
    className={styles.battleScene}
    viewBox="0 0 720 303"
    preserveAspectRatio="none"
    aria-hidden="true"
    focusable="false"
  >
    <defs>
      <filter id="battleFeather" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="1.15" /></filter>
      <filter id="battleGlow" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="2.4" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      <radialGradient id="leftSmoke" cx="50%" cy="50%" r="50%"><stop offset="0" stopColor="#00170d" stopOpacity=".94" /><stop offset=".62" stopColor="#00170d" stopOpacity=".67" /><stop offset="1" stopColor="#00170d" stopOpacity="0" /></radialGradient>
      <radialGradient id="rightSmoke" cx="50%" cy="50%" r="50%"><stop offset="0" stopColor="#190306" stopOpacity=".94" /><stop offset=".62" stopColor="#190306" stopOpacity=".67" /><stop offset="1" stopColor="#190306" stopOpacity="0" /></radialGradient>
      <mask id="longBodyMask" maskUnits="userSpaceOnUse" x="70" y="15" width="305" height="205"><polygon points="90,70 132,46 187,31 243,38 296,65 326,94 327,132 300,160 255,174 205,169 154,154 114,132 96,105" fill="white" filter="url(#battleFeather)" /></mask>
      <mask id="longHeadMask" maskUnits="userSpaceOnUse" x="220" y="65" width="155" height="145"><polygon points="248,86 288,74 328,88 355,116 352,156 330,190 292,198 258,181 238,150 240,112" fill="white" filter="url(#battleFeather)" /></mask>
      <mask id="longFrontLegMask" maskUnits="userSpaceOnUse" x="200" y="130" width="145" height="110"><polygon points="228,139 287,143 319,169 308,212 279,232 249,218 234,188" fill="white" filter="url(#battleFeather)" /></mask>
      <mask id="longRearLegMask" maskUnits="userSpaceOnUse" x="80" y="122" width="150" height="110"><polygon points="102,132 158,137 202,159 198,201 170,223 130,212 102,181" fill="white" filter="url(#battleFeather)" /></mask>
      <mask id="shortBodyMask" maskUnits="userSpaceOnUse" x="345" y="15" width="305" height="205"><polygon points="390,76 424,54 472,38 528,39 586,58 626,86 642,116 632,151 599,177 548,187 495,176 447,159 408,133 388,105" fill="white" filter="url(#battleFeather)" /></mask>
      <mask id="shortHeadMask" maskUnits="userSpaceOnUse" x="345" y="65" width="155" height="145"><polygon points="365,92 401,76 443,83 474,108 481,146 464,181 430,198 393,191 367,163 357,125" fill="white" filter="url(#battleFeather)" /></mask>
      <mask id="shortFrontLegMask" maskUnits="userSpaceOnUse" x="380" y="130" width="145" height="110"><polygon points="401,146 461,142 493,166 487,208 459,230 426,219 408,188" fill="white" filter="url(#battleFeather)" /></mask>
      <mask id="shortRearLegMask" maskUnits="userSpaceOnUse" x="500" y="122" width="150" height="110"><polygon points="518,142 568,132 620,151 635,184 612,216 575,225 540,205 521,176" fill="white" filter="url(#battleFeather)" /></mask>
    </defs>

    <ellipse cx="230" cy="138" rx="195" ry="122" fill="url(#leftSmoke)" />
    <ellipse cx="500" cy="138" rx="195" ry="122" fill="url(#rightSmoke)" />

    <g transform={`translate(${battleShift.toFixed(2)} 0)`}>
      <g transform={`translate(${longBodyX.toFixed(2)} ${longBodyY.toFixed(2)})`}><image href={BATTLE_SOURCE} x="0" y="0" width="720" height="303" preserveAspectRatio="none" mask="url(#longBodyMask)" /></g>
      <g transform={`translate(${longHeadX.toFixed(2)} ${(longBodyY * 0.55).toFixed(2)}) rotate(${(-shove * 0.9).toFixed(2)} 300 137)`}><image href={BATTLE_SOURCE} x="0" y="0" width="720" height="303" preserveAspectRatio="none" mask="url(#longHeadMask)" /></g>
      <g transform={`translate(${(longLift * 3.4).toFixed(2)} ${(-longLift * 7.5).toFixed(2)}) rotate(${(-longLift * 3.4).toFixed(2)} 271 169)`}><image href={BATTLE_SOURCE} x="0" y="0" width="720" height="303" preserveAspectRatio="none" mask="url(#longFrontLegMask)" /></g>
      <g transform={`translate(${(longRear * 2.2).toFixed(2)} ${(-longRear * 3.8).toFixed(2)}) rotate(${(longRear * 2.1).toFixed(2)} 155 165)`}><image href={BATTLE_SOURCE} x="0" y="0" width="720" height="303" preserveAspectRatio="none" mask="url(#longRearLegMask)" /></g>

      <g transform={`translate(${shortBodyX.toFixed(2)} ${shortBodyY.toFixed(2)})`}><image href={BATTLE_SOURCE} x="0" y="0" width="720" height="303" preserveAspectRatio="none" mask="url(#shortBodyMask)" /></g>
      <g transform={`translate(${shortHeadX.toFixed(2)} ${(shortBodyY * 0.55).toFixed(2)}) rotate(${(shove * 0.9).toFixed(2)} 420 137)`}><image href={BATTLE_SOURCE} x="0" y="0" width="720" height="303" preserveAspectRatio="none" mask="url(#shortHeadMask)" /></g>
      <g transform={`translate(${(-shortLift * 3.4).toFixed(2)} ${(-shortLift * 7.5).toFixed(2)}) rotate(${(shortLift * 3.4).toFixed(2)} 449 169)`}><image href={BATTLE_SOURCE} x="0" y="0" width="720" height="303" preserveAspectRatio="none" mask="url(#shortFrontLegMask)" /></g>
      <g transform={`translate(${(-shortRear * 2.2).toFixed(2)} ${(-shortRear * 3.8).toFixed(2)}) rotate(${(-shortRear * 2.1).toFixed(2)} 565 165)`}><image href={BATTLE_SOURCE} x="0" y="0" width="720" height="303" preserveAspectRatio="none" mask="url(#shortRearLegMask)" /></g>

      <g className={styles.impactSparks} filter="url(#battleGlow)" opacity={sparkPulse}>{sparks.map((spark, index) => <circle key={`spark-${index}`} cx={spark.cx} cy={spark.cy} r={index % 5 === 0 ? 1.7 : 1.05} fill="#ffc45e" opacity={spark.opacity} />)}</g>
      <g className={styles.battleDust}>{dust.map((particle, index) => <circle key={`dust-${index}`} cx={particle.cx} cy={particle.cy} r={index % 4 === 0 ? 2.4 : 1.5} fill={particle.side < 0 ? "#4bf2a2" : "#ff6a7d"} opacity={particle.opacity} />)}</g>
    </g>
  </svg>;
}

export function PortfolioImpactBattle({ positions, equity, dataAvailable, updatedAt, marketPressureOverride }: Props) {
  const [timeframe, setTimeframe] = useState<Timeframe>("15m");
  const [pressure, setPressure] = useState<MarketPressurePayload | null>(null);
  const [loadingPressure, setLoadingPressure] = useState(true);
  const [pressureError, setPressureError] = useState("");
  const [displayFrameIndex, setDisplayFrameIndex] = useState(NEUTRAL_FRAME);
  const [battleAnimationFrame, setBattleAnimationFrame] = useState(0);
  const displayFrameRef = useRef(NEUTRAL_FRAME);
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
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
    if (reduced) {
      setBattleAnimationFrame(0);
      return;
    }
    const interval = window.setInterval(() => {
      setBattleAnimationFrame((current) => (current + 1) % BATTLE_LOOP_FRAMES);
    }, BATTLE_FRAME_MS);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    let active = true;
    const cacheKey = `${timeframe}|${symbolKey}`;
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
      return () => { active = false; };
    }

    const cached = pressureCache.current.get(cacheKey);
    if (cached) {
      setPressure(cached);
      setLoadingPressure(false);
      setPressureError("");
    } else {
      setLoadingPressure(true);
      setPressureError("");
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
    };
  }, [timeframe, symbolKey, marketPressureOverride]);

  const currentPressure = pressure ?? { ...dominancePresentation(0), timeframe, symbolsUsed: [], updatedAt: 0 };
  const targetFrameIndex = shareToFrame(currentPressure.longShare);

  useEffect(() => {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
    if (reduced) {
      displayFrameRef.current = targetFrameIndex;
      setDisplayFrameIndex(targetFrameIndex);
      return;
    }
    if (displayFrameRef.current === targetFrameIndex) return;
    const interval = window.setInterval(() => {
      const current = displayFrameRef.current;
      if (current === targetFrameIndex) {
        window.clearInterval(interval);
        return;
      }
      const next = current + (targetFrameIndex > current ? 1 : -1);
      displayFrameRef.current = next;
      setDisplayFrameIndex(next);
      if (next === targetFrameIndex) window.clearInterval(interval);
    }, FRAME_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [targetFrameIndex]);

  const netPnl = snapshot.longPnl + snapshot.shortPnl;
  const equityBasis = equity && Math.abs(equity) > 0.01 ? Math.abs(equity) : 0;
  const netPercent = equityBasis ? netPnl / equityBasis * 100 : null;
  const longPercent = equityBasis ? snapshot.longPnl / equityBasis * 100 : null;
  const shortPercent = equityBasis ? snapshot.shortPnl / equityBasis * 100 : null;
  const scoreLabel = currentPressure.score > 0 ? `+${currentPressure.score}` : String(currentPressure.score);
  const pressureStatus = loadingPressure && !pressure ? "MARKTDRUK WORDT BEREKEND" : pressure?.status ?? "IN EVENWICHT";
  const pressureCaption = pressure
    ? `${pressure.barLabel} · ${TIMEFRAMES.find((item) => item.id === timeframe)?.label} · SCORE ${scoreLabel}${pressure.symbolsUsed.length ? ` · ${pressure.symbolsUsed.length} MARKTEN` : ""}`
    : pressureError ? "MARKTDRUK TIJDELIJK ONBESCHIKBAAR" : "MARKTDRUK";
  const displayLongShare = frameToShare(displayFrameIndex);
  const displayShortShare = 100 - displayLongShare;
  const impactPosition = 50 + (displayLongShare - 50) * 0.10;
  const visualStyle = {
    "--long-share": `${displayLongShare}%`,
    "--impact-x": `${impactPosition}%`,
  } as React.CSSProperties;

  return <div className={styles.module}>
    <div className={styles.timeframes} role="group" aria-label="Marktdruk timeframe">
      {TIMEFRAMES.map((item) => <button key={item.id} type="button" className={item.id === timeframe ? styles.activeTimeframe : ""} aria-pressed={item.id === timeframe} onClick={() => setTimeframe(item.id)}>{item.label}</button>)}
    </div>

    <section
      className={`${styles.card} ${!dataAvailable ? styles.unavailable : ""}`}
      style={visualStyle}
      data-state-index={currentPressure.stateIndex}
      data-frame-index={displayFrameIndex}
      data-target-frame-index={targetFrameIndex}
      data-battle-animation-frame={battleAnimationFrame}
      data-visual-long-share={displayLongShare}
      data-target-long-share={currentPressure.longShare}
      data-timeframe={timeframe}
      data-score={currentPressure.score}
      data-updated-at={updatedAt ?? ""}
      aria-label={`Portfolio impact. Long open P&L ${formatUsd(snapshot.longPnl, true)}, short open P&L ${formatUsd(snapshot.shortPnl, true)}, netto ${formatUsd(netPnl, true)}. Marktdruk ${pressureStatus}.`}
    >
      <span className={styles.scene} aria-hidden="true" />
      <BattleArtwork frame={battleAnimationFrame} longShare={displayLongShare} />
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
          <em className={longPercent === null ? styles.neutral : tone(longPercent)}>{formatPercent(longPercent)}</em>
          <span className={styles.positionCount}>{snapshot.longs.length} posities</span>
        </div>

        <div className={styles.centerPanel}>
          <div className={styles.centerTitle}><i />PORTFOLIO IMPACT</div>
          <strong className={tone(netPnl)}>{formatUsd(netPnl, true)}</strong>
          <span className={netPercent === null ? styles.neutral : tone(netPercent)}>{formatPercent(netPercent)}</span>
        </div>

        <div className={`${styles.sidePanel} ${styles.shortPanel}`}>
          <div className={styles.sideTitle}><i>↘</i><span>SHORTS</span></div>
          <small>Open P&amp;L</small>
          <strong className={tone(snapshot.shortPnl)}>{formatUsd(snapshot.shortPnl, true)}</strong>
          <em className={shortPercent === null ? styles.neutral : tone(shortPercent)}>{formatPercent(shortPercent)}</em>
          <span className={styles.positionCount}>{snapshot.shorts.length} posities</span>
        </div>

        <div className={styles.battleFooter}>
          <div className={styles.status}>{pressureStatus}</div>
          <div className={styles.balanceRow}>
            <div className={`${styles.share} ${styles.longShare}`}><strong>{formatShare(displayLongShare)}%</strong></div>
            <div className={styles.balanceTrack} aria-label={`Marktdruk longs ${formatShare(displayLongShare)} procent, shorts ${formatShare(displayShortShare)} procent`}>
              <span className={styles.longFill} />
              <span className={styles.shortFill} />
              <i />
            </div>
            <div className={`${styles.share} ${styles.shortShare}`}><strong>{formatShare(displayShortShare)}%</strong></div>
          </div>
          <div className={styles.barCaption}>{pressureCaption}</div>
        </div>
      </>}
    </section>
  </div>;
}
