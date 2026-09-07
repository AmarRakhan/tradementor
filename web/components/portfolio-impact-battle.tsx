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
const BATTLE_SOURCE = "/portfolio-impact-premium-reference.webp";
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
      price: numberFrom(componentsRow.price), candles: numberFrom(componentsRow.candles),
      momentum: numberFrom(componentsRow.momentum), trend: numberFrom(componentsRow.trend), breadth: numberFrom(componentsRow.breadth),
    } : undefined,
  };
}

function BattleArtwork({ frame, longShare }: { frame: number; longShare: number }) {
  const phase = frame / BATTLE_LOOP_FRAMES * Math.PI * 2;
  const pressure = Math.max(-1, Math.min(1, (longShare - 50) / 50));
  const intensity = Math.min(1, 0.28 + Math.abs(pressure) * 1.18);
  const shove = Math.sin(phase);
  const brace = Math.sin(phase * 2 + 0.55);
  const battleShift = pressure * 24;
  const shoveAmplitude = 2.3 + intensity * 4.8;
  const legAmplitude = 2.4 + intensity * 7.0;
  const longLift = Math.max(0, Math.sin(phase));
  const shortLift = Math.max(0, Math.sin(phase + Math.PI));
  const longRear = Math.max(0, Math.sin(phase + Math.PI));
  const shortRear = Math.max(0, Math.sin(phase));
  const longHeadX = shove * shoveAmplitude + brace * 0.7 + pressure * 2.2;
  const shortHeadX = -shove * shoveAmplitude - brace * 0.7 + pressure * 2.2;
  const longBodyX = shove * (1.0 + intensity * 1.5) + pressure * 1.4;
  const shortBodyX = -shove * (1.0 + intensity * 1.5) + pressure * 1.4;
  const longBodyY = Math.sin(phase + 0.2) * (0.6 + intensity * 1.1);
  const shortBodyY = Math.sin(phase + Math.PI + 0.2) * (0.6 + intensity * 1.1);
  const eraserOpacity = 0.28 + intensity * 0.20;
  const dustCount = 12 + Math.round(intensity * 12);
  const sparkCount = 10 + Math.round(intensity * 12);

  const dust = Array.from({ length: dustCount }, (_, index) => {
    const seed = index * 1.618 + frame * 0.19;
    const side = index % 2 === 0 ? -1 : 1;
    return {
      cx: side < 0 ? 235 + Math.sin(seed) * 58 : 485 + Math.sin(seed * 1.13) * 58,
      cy: 222 + Math.cos(seed * 0.79) * 8 - (frame % 8) * (0.18 + intensity * 0.36),
      r: 1.0 + (index % 4) * 0.55 + intensity * 0.8,
      opacity: 0.08 + intensity * 0.20 + ((index * 13) % 17) / 100,
    };
  });
  const sparks = Array.from({ length: sparkCount }, (_, index) => {
    const angle = index / sparkCount * Math.PI * 2 + frame * (0.035 + intensity * 0.045);
    const radius = 7 + (index % 6) * (3.5 + intensity * 2.4) + (frame % 5) * 0.8;
    return {
      cx: 360 + Math.cos(angle) * radius,
      cy: 143 + Math.sin(angle) * radius * 0.72 - (frame % 4) * 0.25,
      r: 0.8 + (index % 3) * 0.45,
      opacity: 0.25 + intensity * 0.50,
    };
  });

  return <svg className={styles.battleScene} viewBox="0 0 720 303" preserveAspectRatio="none" aria-hidden="true" focusable="false">
    <defs>
      <filter id="battleFeather" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="1.05" /></filter>
      <filter id="battleGlow" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="2.2" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      <mask id="longSilhouette" maskUnits="userSpaceOnUse" x="40" y="20" width="340" height="225" style={{ maskType: "alpha" }}><polygon points="70,77 110,50 165,29 230,30 286,51 333,83 357,113 351,159 322,196 278,225 209,229 148,210 99,176 75,130" fill="white" filter="url(#battleFeather)" /></mask>
      <mask id="shortSilhouette" maskUnits="userSpaceOnUse" x="340" y="20" width="340" height="225" style={{ maskType: "alpha" }}><polygon points="363,84 402,55 455,33 522,31 581,50 627,78 651,112 648,155 621,192 574,221 510,228 449,213 402,184 373,148" fill="white" filter="url(#battleFeather)" /></mask>
      <mask id="longBodyMask" maskUnits="userSpaceOnUse" x="55" y="18" width="320" height="205" style={{ maskType: "alpha" }}><polygon points="72,74 115,48 170,31 236,36 296,62 333,93 330,130 302,163 257,182 202,176 149,157 104,130 85,105" fill="white" filter="url(#battleFeather)" /></mask>
      <mask id="longHeadMask" maskUnits="userSpaceOnUse" x="225" y="70" width="155" height="140" style={{ maskType: "alpha" }}><polygon points="246,91 286,76 329,86 357,115 354,157 331,193 290,200 256,181 238,148 239,112" fill="white" filter="url(#battleFeather)" /></mask>
      <mask id="longFrontLegMask" maskUnits="userSpaceOnUse" x="196" y="126" width="145" height="116" style={{ maskType: "alpha" }}><polygon points="222,137 284,143 319,169 310,214 278,237 244,219 229,187" fill="white" filter="url(#battleFeather)" /></mask>
      <mask id="longRearLegMask" maskUnits="userSpaceOnUse" x="70" y="122" width="155" height="118" style={{ maskType: "alpha" }}><polygon points="93,132 151,137 202,158 202,203 169,229 126,215 94,183" fill="white" filter="url(#battleFeather)" /></mask>
      <mask id="shortBodyMask" maskUnits="userSpaceOnUse" x="345" y="18" width="320" height="205" style={{ maskType: "alpha" }}><polygon points="389,79 424,55 474,36 532,38 590,58 632,88 647,119 635,154 600,179 549,190 493,178 445,158 407,131 388,105" fill="white" filter="url(#battleFeather)" /></mask>
      <mask id="shortHeadMask" maskUnits="userSpaceOnUse" x="340" y="70" width="155" height="140" style={{ maskType: "alpha" }}><polygon points="365,92 402,77 444,83 477,109 482,147 464,183 429,201 391,190 365,161 356,124" fill="white" filter="url(#battleFeather)" /></mask>
      <mask id="shortFrontLegMask" maskUnits="userSpaceOnUse" x="379" y="126" width="145" height="116" style={{ maskType: "alpha" }}><polygon points="400,145 462,141 496,165 490,210 459,234 425,221 407,188" fill="white" filter="url(#battleFeather)" /></mask>
      <mask id="shortRearLegMask" maskUnits="userSpaceOnUse" x="497" y="122" width="155" height="118" style={{ maskType: "alpha" }}><polygon points="516,139 570,131 623,150 639,184 613,220 574,229 539,207 519,177" fill="white" filter="url(#battleFeather)" /></mask>
    </defs>

    <rect width="720" height="303" fill="#00140b" opacity={eraserOpacity} mask="url(#longSilhouette)" />
    <rect width="720" height="303" fill="#180306" opacity={eraserOpacity} mask="url(#shortSilhouette)" />

    <g transform={`translate(${battleShift.toFixed(2)} 0)`}>
      <g transform={`translate(${longBodyX.toFixed(2)} ${longBodyY.toFixed(2)}) scale(1.015 1.015)`}><image href={BATTLE_SOURCE} x="0" y="0" width="720" height="303" preserveAspectRatio="none" mask="url(#longBodyMask)" /></g>
      <g transform={`translate(${longHeadX.toFixed(2)} ${(longBodyY * 0.45).toFixed(2)}) rotate(${(-shove * (0.5 + intensity)).toFixed(2)} 302 139)`}><image href={BATTLE_SOURCE} x="0" y="0" width="720" height="303" preserveAspectRatio="none" mask="url(#longHeadMask)" /></g>
      <g transform={`translate(${(longLift * legAmplitude * 0.45).toFixed(2)} ${(-longLift * legAmplitude).toFixed(2)}) rotate(${(-longLift * (2.2 + intensity * 2.4)).toFixed(2)} 271 169)`}><image href={BATTLE_SOURCE} x="0" y="0" width="720" height="303" preserveAspectRatio="none" mask="url(#longFrontLegMask)" /></g>
      <g transform={`translate(${(longRear * legAmplitude * 0.28).toFixed(2)} ${(-longRear * legAmplitude * 0.48).toFixed(2)}) rotate(${(longRear * (1.2 + intensity * 2)).toFixed(2)} 155 168)`}><image href={BATTLE_SOURCE} x="0" y="0" width="720" height="303" preserveAspectRatio="none" mask="url(#longRearLegMask)" /></g>

      <g transform={`translate(${shortBodyX.toFixed(2)} ${shortBodyY.toFixed(2)}) scale(1.015 1.015)`}><image href={BATTLE_SOURCE} x="0" y="0" width="720" height="303" preserveAspectRatio="none" mask="url(#shortBodyMask)" /></g>
      <g transform={`translate(${shortHeadX.toFixed(2)} ${(shortBodyY * 0.45).toFixed(2)}) rotate(${(shove * (0.5 + intensity)).toFixed(2)} 418 139)`}><image href={BATTLE_SOURCE} x="0" y="0" width="720" height="303" preserveAspectRatio="none" mask="url(#shortHeadMask)" /></g>
      <g transform={`translate(${(-shortLift * legAmplitude * 0.45).toFixed(2)} ${(-shortLift * legAmplitude).toFixed(2)}) rotate(${(shortLift * (2.2 + intensity * 2.4)).toFixed(2)} 449 169)`}><image href={BATTLE_SOURCE} x="0" y="0" width="720" height="303" preserveAspectRatio="none" mask="url(#shortFrontLegMask)" /></g>
      <g transform={`translate(${(-shortRear * legAmplitude * 0.28).toFixed(2)} ${(-shortRear * legAmplitude * 0.48).toFixed(2)}) rotate(${(-shortRear * (1.2 + intensity * 2)).toFixed(2)} 565 168)`}><image href={BATTLE_SOURCE} x="0" y="0" width="720" height="303" preserveAspectRatio="none" mask="url(#shortRearLegMask)" /></g>
    </g>

    <g className={styles.battleDust}>
      {dust.map((particle, index) => <circle key={index} cx={particle.cx} cy={particle.cy} r={particle.r} fill={index % 2 ? "#ffb15b" : "#b1e78d"} opacity={particle.opacity} />)}
    </g>
    <g className={styles.impactSparks} filter="url(#battleGlow)">
      {sparks.map((spark, index) => <circle key={index} cx={spark.cx} cy={spark.cy} r={spark.r} fill={index % 3 === 0 ? "#fff4bc" : "#ffb342"} opacity={spark.opacity} />)}
      <circle cx="360" cy="143" r={4.8 + intensity * 3.8 + Math.max(0, shove) * 1.4} fill="#fff7c9" opacity={0.55 + intensity * 0.30} />
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
    return Array.from(exposureBySymbol.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 16).map(([symbol]) => symbol);
  }, [positions]);
  const symbolKey = marketSymbols.join(",");

  useEffect(() => {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
    if (reduced) return;
    const interval = window.setInterval(() => setBattleAnimationFrame((current) => (current + 1) % BATTLE_LOOP_FRAMES), BATTLE_FRAME_MS);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    let active = true;
    const cacheKey = `${timeframe}|${symbolKey}`;
    const overrideScore = marketPressureOverride?.[timeframe];
    if (Number.isFinite(Number(overrideScore))) {
      const presentation = dominancePresentation(Number(overrideScore));
      setPressure({ timeframe, score: presentation.score, longShare: presentation.longShare, shortShare: presentation.shortShare, stateIndex: presentation.stateIndex, status: presentation.status, barLabel: presentation.barLabel, symbolsUsed: marketSymbols.length ? marketSymbols : ["BTCUSDT", "ETHUSDT", "SOLUSDT"], updatedAt: Date.now() });
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
    return () => { active = false; window.clearInterval(interval); };
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
      if (current === targetFrameIndex) { window.clearInterval(interval); return; }
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
  const pressureCaption = pressure ? `${pressure.barLabel} · ${TIMEFRAMES.find((item) => item.id === timeframe)?.label} · SCORE ${scoreLabel}${pressure.symbolsUsed.length ? ` · ${pressure.symbolsUsed.length} MARKTEN` : ""}` : pressureError ? "MARKTDRUK TIJDELIJK ONBESCHIKBAAR" : "MARKTDRUK";
  const displayLongShare = frameToShare(displayFrameIndex);
  const displayShortShare = 100 - displayLongShare;
  const impactPosition = 50 + (displayLongShare - 50) * 0.10;
  const visualIntensity = Math.min(1, 0.28 + Math.abs(displayLongShare - 50) / 50 * 1.18);
  const visualStyle = { "--long-share": `${displayLongShare}%`, "--impact-x": `${impactPosition}%`, "--battle-intensity": visualIntensity } as React.CSSProperties;
  const legacyFramePath = framePath(displayFrameIndex);

  return <div className={styles.module}>
    <div className={styles.timeframes} role="group" aria-label="Marktdruk timeframe">
      {TIMEFRAMES.map((item) => <button key={item.id} type="button" className={item.id === timeframe ? styles.activeTimeframe : ""} aria-pressed={item.id === timeframe} onClick={() => setTimeframe(item.id)}>{item.label}</button>)}
    </div>

    <section className={`${styles.card} ${!dataAvailable ? styles.unavailable : ""}`} style={visualStyle}
      data-state-index={currentPressure.stateIndex} data-frame-index={displayFrameIndex} data-target-frame-index={targetFrameIndex}
      data-visual-long-share={displayLongShare} data-target-long-share={currentPressure.longShare} data-timeframe={timeframe} data-score={currentPressure.score}
      data-updated-at={updatedAt ?? ""} data-battle-animation-frame={battleAnimationFrame} data-battle-intensity={visualIntensity.toFixed(3)} data-legacy-frame-path={legacyFramePath}
      aria-label={`Portfolio impact. Long open P&L ${formatUsd(snapshot.longPnl, true)}, short open P&L ${formatUsd(snapshot.shortPnl, true)}, netto ${formatUsd(netPnl, true)}. Marktdruk ${pressureStatus}.`}>
      <img className={styles.scene} src="/portfolio-impact-premium-clean.webp" alt="" aria-hidden="true" />
      <BattleArtwork frame={battleAnimationFrame} longShare={displayLongShare} />
      <div className={styles.vignette} aria-hidden="true" />

      {!dataAvailable ? <div className={styles.loadingCopy}><span>PORTFOLIO IMPACT</span><strong>Exchangegegevens laden…</strong><small>Marktdruk blijft read-only en opent of sluit nooit posities.</small></div> : <>
        <div className={`${styles.sidePanel} ${styles.longPanel}`}><div className={styles.sideTitle}><span>LONGS</span><i>↗</i></div><small>Open P&amp;L</small><strong className={tone(snapshot.longPnl)}>{formatUsd(snapshot.longPnl, true)}</strong><em className={tone(snapshot.longPnl)}>{formatPercent(longPercent)}</em><span className={styles.positionCount}>{snapshot.longs.length} posities</span></div>
        <div className={styles.centerPanel}><div className={styles.centerTitle}><i />PORTFOLIO IMPACT</div><strong className={tone(netPnl)}>{formatUsd(netPnl, true)}</strong><span className={tone(netPnl)}>{formatPercent(netPercent)}</span></div>
        <div className={`${styles.sidePanel} ${styles.shortPanel}`}><div className={styles.sideTitle}><i>↘</i><span>SHORTS</span></div><small>Open P&amp;L</small><strong className={tone(snapshot.shortPnl)}>{formatUsd(snapshot.shortPnl, true)}</strong><em className={tone(snapshot.shortPnl)}>{formatPercent(shortPercent)}</em><span className={styles.positionCount}>{snapshot.shorts.length} posities</span></div>
      </>}

      <div className={styles.battleFooter}><div className={styles.status}>{pressureStatus}</div><div className={styles.balanceRow}><div className={`${styles.share} ${styles.longShare}`}><strong>{formatShare(displayLongShare)}%</strong></div><div className={styles.balanceTrack} aria-hidden="true"><div className={styles.longFill} /><div className={styles.shortFill} /><i /></div><div className={`${styles.share} ${styles.shortShare}`}><strong>{formatShare(displayShortShare)}%</strong></div></div><div className={styles.barCaption}>{pressureCaption}</div></div>
    </section>
  </div>;
}
