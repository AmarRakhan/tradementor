"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import {
  battleStatus,
  bollingerScore,
  clampBollingerScore,
  legacyPressureOverrideToBollingerScore,
  scoreToTimelineTime,
  shouldAnimateScore,
  timeframeToAsterInterval,
  transitionDurationMs,
} from "@/lib/bollinger-battle.mjs";
import styles from "./portfolio-impact-battle.module.css";
import videoStyles from "./portfolio-impact-bull-bear-video.module.css";

type BattlePosition = Record<string, unknown>;
type Timeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "24h";
type AsterMarketRow = Record<string, unknown>;
type BollingerSnapshot = {
  timeframe: Timeframe;
  price: number;
  lower: number;
  middle: number;
  upper: number;
  score: number;
  updatedAt: number;
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
const MASTER_SOURCE = "/portfolio-impact-bull-bear-master.mp4";
const POSTER_SOURCE = "/portfolio-impact-bull-bear-neutral.webp";
const SEEK_EPSILON_SECONDS = 1 / 30;
const money = new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const percent = new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const scoreNumber = new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

function numberFrom(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}
function finiteNumber(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
function positionSide(position: unknown) {
  if (!position || typeof position !== "object") return "";
  return String((position as BattlePosition).side ?? "").toLowerCase();
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
function marketRows(value: unknown): AsterMarketRow[] {
  if (!value || typeof value !== "object") return [];
  const rows = (value as Record<string, unknown>).markets;
  return Array.isArray(rows) ? rows.filter((row): row is AsterMarketRow => Boolean(row && typeof row === "object")) : [];
}
function btcRow(value: unknown) {
  return marketRows(value).find((row) => String(row.symbol ?? "").toUpperCase().replace(/[\/_-]/g, "") === "BTCUSDT") ?? null;
}
function parseBollingerSnapshot(enriched: unknown, base: unknown, timeframe: Timeframe): BollingerSnapshot | null {
  const bandRow = btcRow(enriched);
  const priceRow = btcRow(base);
  if (!bandRow || !priceRow) return null;
  const lower = finiteNumber(bandRow.bbLower);
  const middle = finiteNumber(bandRow.bbMiddle);
  const upper = finiteNumber(bandRow.bbUpper);
  const price = finiteNumber(priceRow.lastPrice ?? priceRow.price ?? priceRow.markPrice);
  if (lower === null || middle === null || upper === null || price === null) return null;
  const score = bollingerScore(price, lower, upper);
  if (score === null) return null;
  return { timeframe, price, lower, middle, upper, score, updatedAt: Date.now() };
}
function easeInOutCubic(value: number) {
  return value < 0.5 ? 4 * value * value * value : 1 - Math.pow(-2 * value + 2, 3) / 2;
}

export function PortfolioImpactBattle({ positions, equity, dataAvailable, updatedAt, marketPressureOverride }: Props) {
  const [timeframe, setTimeframe] = useState<Timeframe>("15m");
  const [bollinger, setBollinger] = useState<BollingerSnapshot | null>(null);
  const [loadingPressure, setLoadingPressure] = useState(true);
  const [pressureError, setPressureError] = useState("");
  const [displayScore, setDisplayScore] = useState(50);
  const [videoReady, setVideoReady] = useState(false);
  const [videoFailed, setVideoFailed] = useState(false);
  const displayScoreRef = useRef(50);
  const animationRef = useRef<number | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const bollingerCache = useRef(new Map<Timeframe, BollingerSnapshot>());

  const snapshot = useMemo(() => {
    const longs = positions.filter((position) => positionSide(position) === "long");
    const shorts = positions.filter((position) => positionSide(position) === "short");
    const longPnl = longs.reduce((total, position) => total + positionPnl(position), 0);
    const shortPnl = shorts.reduce((total, position) => total + positionPnl(position), 0);
    return { longs, shorts, longPnl, shortPnl };
  }, [positions]);

  useEffect(() => {
    let active = true;
    const overrideScore = marketPressureOverride?.[timeframe];
    if (Number.isFinite(Number(overrideScore))) {
      const score = legacyPressureOverrideToBollingerScore(Number(overrideScore));
      const mock = { timeframe, price: 0, lower: 0, middle: 0, upper: 0, score, updatedAt: Date.now() };
      setBollinger(mock);
      setLoadingPressure(false);
      setPressureError("");
      return () => { active = false; };
    }

    const cached = bollingerCache.current.get(timeframe);
    if (cached) {
      setBollinger(cached);
      setLoadingPressure(false);
      setPressureError("");
    } else {
      setLoadingPressure(true);
      setPressureError("");
    }

    const load = async (quiet = false) => {
      if (!quiet && !bollingerCache.current.has(timeframe)) setLoadingPressure(true);
      try {
        const interval = timeframeToAsterInterval(timeframe);
        const [enriched, base] = await Promise.all([
          authenticatedRequest(`/api/markets/aster?mode=enrich&symbols=BTCUSDT&interval=${encodeURIComponent(interval)}`),
          authenticatedRequest("/api/markets/aster"),
        ]);
        const next = parseBollingerSnapshot(enriched, base, timeframe);
        if (!active) return;
        if (!next) throw new Error("BTC Bollinger-data tijdelijk niet beschikbaar");
        bollingerCache.current.set(timeframe, next);
        setBollinger(next);
        setPressureError("");
        setLoadingPressure(false);
      } catch (reason) {
        if (!active) return;
        setLoadingPressure(false);
        setPressureError(reason instanceof Error ? reason.message : "BTC Bollinger-data tijdelijk niet beschikbaar");
      }
    };

    void load(Boolean(cached));
    const refresh = window.setInterval(() => { void load(true); }, REFRESH_MS[timeframe]);
    return () => { active = false; window.clearInterval(refresh); };
  }, [timeframe, marketPressureOverride]);

  const targetScore = clampBollingerScore(bollinger?.score ?? 50);

  useEffect(() => {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
    const video = videoRef.current;
    const seek = (score: number) => {
      if (!video || video.readyState < 1 || !Number.isFinite(video.duration) || video.duration <= 0) return;
      const targetTime = Math.min(Math.max(0, scoreToTimelineTime(score, video.duration)), Math.max(0, video.duration - 0.001));
      if (Math.abs(video.currentTime - targetTime) >= SEEK_EPSILON_SECONDS) video.currentTime = targetTime;
    };

    if (animationRef.current !== null) cancelAnimationFrame(animationRef.current);
    const from = displayScoreRef.current;
    if (reduced || !shouldAnimateScore(from, targetScore)) {
      if (reduced && from !== targetScore) {
        displayScoreRef.current = targetScore;
        setDisplayScore(targetScore);
        seek(targetScore);
      }
      return;
    }

    const started = performance.now();
    const duration = transitionDurationMs(from, targetScore);
    const tick = (now: number) => {
      const progress = Math.min(1, Math.max(0, (now - started) / duration));
      const next = from + (targetScore - from) * easeInOutCubic(progress);
      displayScoreRef.current = next;
      setDisplayScore(next);
      seek(next);
      if (progress < 1) animationRef.current = requestAnimationFrame(tick);
      else animationRef.current = null;
    };
    animationRef.current = requestAnimationFrame(tick);
    return () => {
      if (animationRef.current !== null) cancelAnimationFrame(animationRef.current);
      animationRef.current = null;
    };
  }, [targetScore]);

  useEffect(() => () => {
    if (animationRef.current !== null) cancelAnimationFrame(animationRef.current);
  }, []);

  const syncVideoToScore = () => {
    const video = videoRef.current;
    if (!video || video.readyState < 1 || !Number.isFinite(video.duration) || video.duration <= 0) return;
    const targetTime = Math.min(Math.max(0, scoreToTimelineTime(displayScoreRef.current, video.duration)), Math.max(0, video.duration - 0.001));
    video.pause();
    video.currentTime = targetTime;
  };

  const netPnl = snapshot.longPnl + snapshot.shortPnl;
  const equityBasis = equity && Math.abs(equity) > 0.01 ? Math.abs(equity) : 0;
  const netPercent = equityBasis ? netPnl / equityBasis * 100 : null;
  const longPercent = equityBasis ? snapshot.longPnl / equityBasis * 100 : null;
  const shortPercent = equityBasis ? snapshot.shortPnl / equityBasis * 100 : null;
  const displayLongShare = clampBollingerScore(displayScore);
  const displayShortShare = 100 - displayLongShare;
  const pressureStatus = loadingPressure && !bollinger ? "BTC BOLLINGER WORDT BEREKEND" : battleStatus(displayLongShare);
  const timeframeLabel = TIMEFRAMES.find((item) => item.id === timeframe)?.label ?? timeframe;
  const pressureCaption = bollinger
    ? `BTCUSDT · ${timeframeLabel} · BOLLINGER ${scoreNumber.format(targetScore)}%${bollinger.price > 0 ? ` · $${money.format(bollinger.price)}` : ""}`
    : pressureError ? "BTC BOLLINGER TIJDELIJK ONBESCHIKBAAR" : "BTC BOLLINGER";
  const impactPosition = 50 + (displayLongShare - 50) * 0.10;
  const visualIntensity = Math.min(1, 0.28 + Math.abs(displayLongShare - 50) / 50 * 1.18);
  const visualStyle = { "--long-share": `${displayLongShare}%`, "--impact-x": `${impactPosition}%`, "--battle-intensity": visualIntensity } as React.CSSProperties;

  return <div className={styles.module}>
    <div className={styles.timeframes} role="group" aria-label="BTC Bollinger timeframe">
      {TIMEFRAMES.map((item) => <button key={item.id} type="button" className={item.id === timeframe ? styles.activeTimeframe : ""} aria-pressed={item.id === timeframe} onClick={() => setTimeframe(item.id)}>{item.label}</button>)}
    </div>

    <section className={`${styles.card} ${!dataAvailable ? styles.unavailable : ""}`} style={visualStyle}
      data-bollinger-score={targetScore.toFixed(3)} data-visual-long-share={displayLongShare.toFixed(3)} data-target-long-share={targetScore.toFixed(3)}
      data-timeframe={timeframe} data-updated-at={bollinger?.updatedAt ?? updatedAt ?? ""} data-video-ready={videoReady ? "true" : "false"} data-video-failed={videoFailed ? "true" : "false"}
      aria-label={`Portfolio impact. Long open P&L ${formatUsd(snapshot.longPnl, true)}, short open P&L ${formatUsd(snapshot.shortPnl, true)}, netto ${formatUsd(netPnl, true)}. BTC Bollinger ${scoreNumber.format(targetScore)} procent. ${pressureStatus}.`}>
      <img className={videoStyles.poster} src={POSTER_SOURCE} alt="" aria-hidden="true" />
      {!videoFailed ? <video ref={videoRef} className={`${videoStyles.video} ${videoReady ? videoStyles.videoReady : ""}`} src={MASTER_SOURCE} poster={POSTER_SOURCE}
        preload="auto" muted playsInline disablePictureInPicture aria-hidden="true" tabIndex={-1}
        onLoadedMetadata={syncVideoToScore}
        onCanPlay={() => { syncVideoToScore(); setVideoReady(true); }}
        onError={() => { setVideoFailed(true); setVideoReady(false); }} /> : null}
      <div className={styles.vignette} aria-hidden="true" />

      {!dataAvailable ? <div className={styles.loadingCopy}><span>PORTFOLIO IMPACT</span><strong>Exchangegegevens laden…</strong><small>De Bull vs Bear-visualisatie is read-only en opent of sluit nooit posities.</small></div> : <>
        <div className={`${styles.sidePanel} ${styles.longPanel}`}><div className={styles.sideTitle}><span>LONGS</span><i>↗</i></div><small>Open P&amp;L</small><strong className={tone(snapshot.longPnl)}>{formatUsd(snapshot.longPnl, true)}</strong><em className={tone(snapshot.longPnl)}>{formatPercent(longPercent)}</em><span className={styles.positionCount}>{snapshot.longs.length} posities</span></div>
        <div className={styles.centerPanel}><div className={styles.centerTitle}><i />PORTFOLIO IMPACT</div><strong className={tone(netPnl)}>{formatUsd(netPnl, true)}</strong><span className={tone(netPnl)}>{formatPercent(netPercent)}</span></div>
        <div className={`${styles.sidePanel} ${styles.shortPanel}`}><div className={styles.sideTitle}><i>↘</i><span>SHORTS</span></div><small>Open P&amp;L</small><strong className={tone(snapshot.shortPnl)}>{formatUsd(snapshot.shortPnl, true)}</strong><em className={tone(snapshot.shortPnl)}>{formatPercent(shortPercent)}</em><span className={styles.positionCount}>{snapshot.shorts.length} posities</span></div>
      </>}

      <div className={styles.battleFooter}><div className={styles.status}>{pressureStatus}</div><div className={styles.balanceRow}><div className={`${styles.share} ${styles.longShare}`}><strong>{formatShare(displayLongShare)}%</strong></div><div className={styles.balanceTrack} aria-hidden="true"><div className={styles.longFill} /><div className={styles.shortFill} /><i /></div><div className={`${styles.share} ${styles.shortShare}`}><strong>{formatShare(displayShortShare)}%</strong></div></div><div className={styles.barCaption}>{pressureCaption}</div></div>
    </section>
  </div>;
}
