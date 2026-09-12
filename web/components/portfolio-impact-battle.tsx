"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import {
  battleStatus,
  bollingerScore,
  clampBollingerScore,
  legacyPressureOverrideToBollingerScore,
  scoreToTimelineTime,
  timeframeToAsterInterval,
} from "@/lib/bollinger-battle.mjs";
import styles from "./portfolio-impact-battle.module.css";
import videoStyles from "./portfolio-impact-bull-bear-video.module.css";

type BattlePosition = Record<string, unknown>;
type Timeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "24h";
type PlaybackDirection = "forward" | "reverse";
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
const MASTER_SOURCE = "/api/media/bull-bear-master?v=3";
const REVERSE_SOURCE = "/api/media/bull-bear-master?direction=reverse&v=3";
const POSTER_SOURCE = "/portfolio-impact-bull-bear-neutral.webp";
const ASTER_BTC_MARK_STREAM = "wss://fstream.asterdex.com/ws/btcusdt@markPrice@1s";
const SCORE_SMOOTHING_MS = 1_250;
const IDLE_SWAY_SCORE = 1.8;
const IDLE_PERIOD_MS = 2_800;
const DIRECTION_SWITCH_SCORE = 0.18;
const MIN_PLAYBACK_RATE = 0.12;
const MAX_PLAYBACK_RATE = 1;
const UI_UPDATE_MS = 100;
const CROSSFADE_MS = 180;
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
function parseBollingerSnapshot(value: unknown, timeframe: Timeframe): BollingerSnapshot | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  if (String(row.symbol ?? "").toUpperCase().replace(/[\/_-]/g, "") !== "BTCUSDT") return null;
  const lower = finiteNumber(row.lower);
  const middle = finiteNumber(row.middle);
  const upper = finiteNumber(row.upper);
  const price = finiteNumber(row.price);
  const score = finiteNumber(row.score);
  if (lower === null || middle === null || upper === null || price === null || score === null || !(upper > lower)) return null;
  return {
    timeframe,
    price,
    lower,
    middle,
    upper,
    score: clampBollingerScore(score),
    updatedAt: finiteNumber(row.updatedAt) ?? Date.now(),
  };
}
function timelineTimeForDirection(score: number, duration: number, direction: PlaybackDirection) {
  const forwardTime = scoreToTimelineTime(score, duration);
  return direction === "forward" ? forwardTime : Math.max(0, duration - forwardTime);
}
function scoreFromVideo(video: HTMLVideoElement, direction: PlaybackDirection) {
  if (!Number.isFinite(video.duration) || video.duration <= 0 || !Number.isFinite(video.currentTime)) return null;
  const progress = Math.min(1, Math.max(0, video.currentTime / video.duration));
  return clampBollingerScore(direction === "forward" ? progress * 100 : (1 - progress) * 100);
}
function playbackRateForGap(scoreGap: number, duration: number) {
  if (!Number.isFinite(duration) || duration <= 0) return 0.35;
  const scorePerSecond = Math.min(8, Math.max(1, Math.abs(scoreGap) * 1.65 + 0.85));
  return Math.min(MAX_PLAYBACK_RATE, Math.max(MIN_PLAYBACK_RATE, scorePerSecond * duration / 100));
}

export function PortfolioImpactBattle({ positions, equity, dataAvailable, updatedAt, marketPressureOverride }: Props) {
  const [timeframe, setTimeframe] = useState<Timeframe>("15m");
  const [bollinger, setBollinger] = useState<BollingerSnapshot | null>(null);
  const [loadingPressure, setLoadingPressure] = useState(true);
  const [pressureError, setPressureError] = useState("");
  const [displayScore, setDisplayScore] = useState(50);
  const [livePrice, setLivePrice] = useState<number | null>(null);
  const [livePriceAt, setLivePriceAt] = useState<number | null>(null);
  const [marketConnected, setMarketConnected] = useState(false);
  const [forwardReady, setForwardReady] = useState(false);
  const [reverseReady, setReverseReady] = useState(false);
  const [forwardFailed, setForwardFailed] = useState(false);
  const [reverseFailed, setReverseFailed] = useState(false);
  const [activeDirection, setActiveDirection] = useState<PlaybackDirection>("forward");
  const displayScoreRef = useRef(50);
  const targetScoreRef = useRef(50);
  const filmScoreRef = useRef(50);
  const activeDirectionRef = useRef<PlaybackDirection>("forward");
  const animationRef = useRef<number | null>(null);
  const switchFallbackRef = useRef<number | null>(null);
  const oldVideoPauseRef = useRef<number | null>(null);
  const switchingDirectionRef = useRef(false);
  const forwardVideoRef = useRef<HTMLVideoElement | null>(null);
  const reverseVideoRef = useRef<HTMLVideoElement | null>(null);
  const bollingerCache = useRef(new Map<Timeframe, BollingerSnapshot>());
  const lastValidTargetRef = useRef(50);

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
      setBollinger(null);
      setLoadingPressure(true);
      setPressureError("");
    }

    const load = async (quiet = false) => {
      if (!quiet && !bollingerCache.current.has(timeframe)) setLoadingPressure(true);
      try {
        const interval = timeframeToAsterInterval(timeframe);
        const payload = await authenticatedRequest(`/api/markets/aster/btc-bollinger?interval=${encodeURIComponent(interval)}`);
        const next = parseBollingerSnapshot(payload, timeframe);
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

  useEffect(() => {
    if (typeof WebSocket === "undefined") return;
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let stopped = false;
    let retryMs = 1_000;

    const connect = () => {
      if (stopped) return;
      socket = new WebSocket(ASTER_BTC_MARK_STREAM);
      socket.onopen = () => {
        retryMs = 1_000;
        setMarketConnected(true);
      };
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(String(event.data || "")) as Record<string, unknown>;
          const price = finiteNumber(payload.p ?? payload.markPrice);
          if (price === null || price <= 0) return;
          setLivePrice(price);
          setLivePriceAt(finiteNumber(payload.E ?? payload.eventTime) ?? Date.now());
        } catch {
          // Ignore malformed public ticker frames; the last valid price remains authoritative.
        }
      };
      socket.onerror = () => {
        try { socket?.close(); } catch { /* reconnect is handled by onclose */ }
      };
      socket.onclose = () => {
        setMarketConnected(false);
        if (stopped) return;
        reconnectTimer = window.setTimeout(connect, retryMs);
        retryMs = Math.min(15_000, retryMs * 2);
      };
    };

    connect();
    return () => {
      stopped = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);

  const calculatedTargetScore = useMemo(() => {
    const overrideScore = marketPressureOverride?.[timeframe];
    if (Number.isFinite(Number(overrideScore))) return legacyPressureOverrideToBollingerScore(Number(overrideScore));
    if (!bollinger || !(bollinger.upper > bollinger.lower)) return null;
    const price = livePrice && livePrice > 0 ? livePrice : bollinger.price;
    return bollingerScore(price, bollinger.lower, bollinger.upper);
  }, [bollinger, livePrice, marketPressureOverride, timeframe]);
  const targetScore = clampBollingerScore(calculatedTargetScore ?? lastValidTargetRef.current);

  useEffect(() => {
    if (calculatedTargetScore !== null && Number.isFinite(calculatedTargetScore)) {
      lastValidTargetRef.current = clampBollingerScore(calculatedTargetScore);
    }
    targetScoreRef.current = clampBollingerScore(calculatedTargetScore ?? lastValidTargetRef.current);
  }, [calculatedTargetScore]);

  const syncVideoAtCurrentScore = (direction: PlaybackDirection) => {
    const video = direction === "forward" ? forwardVideoRef.current : reverseVideoRef.current;
    if (!video || video.readyState < 1 || !Number.isFinite(video.duration) || video.duration <= 0) return;
    const syncTime = timelineTimeForDirection(filmScoreRef.current, video.duration, direction);
    video.pause();
    if (Math.abs(video.currentTime - syncTime) > 0.025) video.currentTime = syncTime;
  };

  useEffect(() => {
    if (!forwardReady || forwardFailed) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
    if (reduced) {
      displayScoreRef.current = targetScoreRef.current;
      filmScoreRef.current = targetScoreRef.current;
      setDisplayScore(targetScoreRef.current);
      syncVideoAtCurrentScore("forward");
      return;
    }

    let stopped = false;
    let lastTick = performance.now();
    let lastUiUpdate = 0;

    const videoFor = (direction: PlaybackDirection) => direction === "forward" ? forwardVideoRef.current : reverseVideoRef.current;
    const readyFor = (direction: PlaybackDirection) => direction === "forward" ? forwardReady : reverseReady && !reverseFailed;

    const activateDirection = (nextDirection: PlaybackDirection, score: number, playbackRate: number) => {
      if (stopped || switchingDirectionRef.current || nextDirection === activeDirectionRef.current || !readyFor(nextDirection)) return;
      const nextVideo = videoFor(nextDirection);
      const oldVideo = videoFor(activeDirectionRef.current);
      if (!nextVideo || nextVideo.readyState < 1 || !Number.isFinite(nextVideo.duration) || nextVideo.duration <= 0) return;
      switchingDirectionRef.current = true;
      nextVideo.pause();
      nextVideo.playbackRate = playbackRate;
      const syncTime = timelineTimeForDirection(score, nextVideo.duration, nextDirection);

      let activated = false;
      const activate = () => {
        if (activated || stopped) return;
        activated = true;
        if (switchFallbackRef.current !== null) window.clearTimeout(switchFallbackRef.current);
        switchFallbackRef.current = null;
        nextVideo.playbackRate = playbackRate;
        void nextVideo.play().catch(() => undefined);
        activeDirectionRef.current = nextDirection;
        setActiveDirection(nextDirection);
        filmScoreRef.current = score;
        if (oldVideoPauseRef.current !== null) window.clearTimeout(oldVideoPauseRef.current);
        oldVideoPauseRef.current = window.setTimeout(() => oldVideo?.pause(), CROSSFADE_MS);
        switchingDirectionRef.current = false;
      };

      if (Math.abs(nextVideo.currentTime - syncTime) <= 0.025) {
        activate();
      } else {
        nextVideo.addEventListener("seeked", activate, { once: true });
        nextVideo.currentTime = syncTime;
        switchFallbackRef.current = window.setTimeout(activate, 260);
      }
    };

    const tick = (now: number) => {
      if (stopped) return;
      const elapsedMs = Math.min(120, Math.max(0, now - lastTick));
      lastTick = now;
      const smoothing = 1 - Math.exp(-elapsedMs / SCORE_SMOOTHING_MS);
      const currentMarketScore = displayScoreRef.current;
      const marketTarget = targetScoreRef.current;
      const nextMarketScore = clampBollingerScore(currentMarketScore + (marketTarget - currentMarketScore) * smoothing);
      displayScoreRef.current = nextMarketScore;

      const marketGap = Math.abs(marketTarget - nextMarketScore);
      const idleAmplitude = marketGap > 4 ? 0.45 : IDLE_SWAY_SCORE;
      const idleCenter = Math.min(100 - idleAmplitude, Math.max(idleAmplitude, nextMarketScore));
      const idleOffset = Math.sin((now / IDLE_PERIOD_MS) * Math.PI * 2) * idleAmplitude;
      const desiredFilmScore = clampBollingerScore(idleCenter + idleOffset);

      const currentDirection = activeDirectionRef.current;
      const activeVideo = videoFor(currentDirection);
      if (activeVideo) {
        const mediaScore = scoreFromVideo(activeVideo, currentDirection);
        if (mediaScore !== null) filmScoreRef.current = mediaScore;
      }
      const filmGap = desiredFilmScore - filmScoreRef.current;
      const desiredDirection: PlaybackDirection = filmGap > DIRECTION_SWITCH_SCORE
        ? "forward"
        : filmGap < -DIRECTION_SWITCH_SCORE
          ? "reverse"
          : currentDirection;
      const activeDuration = activeVideo && Number.isFinite(activeVideo.duration) && activeVideo.duration > 0 ? activeVideo.duration : 12;
      const rate = playbackRateForGap(filmGap, activeDuration);

      if (desiredDirection !== currentDirection && readyFor(desiredDirection)) {
        activateDirection(desiredDirection, filmScoreRef.current, rate);
      } else if (activeVideo && activeVideo.readyState >= 2 && !switchingDirectionRef.current) {
        activeVideo.playbackRate = rate;
        if (activeVideo.paused && !activeVideo.ended) void activeVideo.play().catch(() => undefined);
      }

      if (now - lastUiUpdate >= UI_UPDATE_MS) {
        lastUiUpdate = now;
        setDisplayScore(nextMarketScore);
      }
      animationRef.current = requestAnimationFrame(tick);
    };

    const initial = forwardVideoRef.current;
    if (initial && activeDirectionRef.current === "forward") {
      initial.playbackRate = 0.35;
      void initial.play().catch(() => undefined);
    }
    animationRef.current = requestAnimationFrame(tick);
    return () => {
      stopped = true;
      if (animationRef.current !== null) cancelAnimationFrame(animationRef.current);
      animationRef.current = null;
      if (switchFallbackRef.current !== null) window.clearTimeout(switchFallbackRef.current);
      switchFallbackRef.current = null;
      if (oldVideoPauseRef.current !== null) window.clearTimeout(oldVideoPauseRef.current);
      oldVideoPauseRef.current = null;
      forwardVideoRef.current?.pause();
      reverseVideoRef.current?.pause();
      switchingDirectionRef.current = false;
    };
  }, [forwardFailed, forwardReady, reverseFailed, reverseReady]);

  const netPnl = snapshot.longPnl + snapshot.shortPnl;
  const equityBasis = equity && Math.abs(equity) > 0.01 ? Math.abs(equity) : 0;
  const netPercent = equityBasis ? netPnl / equityBasis * 100 : null;
  const longPercent = equityBasis ? snapshot.longPnl / equityBasis * 100 : null;
  const shortPercent = equityBasis ? snapshot.shortPnl / equityBasis * 100 : null;
  const displayLongShare = clampBollingerScore(displayScore);
  const displayShortShare = 100 - displayLongShare;
  const pressureStatus = loadingPressure && !bollinger ? "BTC BOLLINGER WORDT BEREKEND" : battleStatus(displayLongShare);
  const timeframeLabel = TIMEFRAMES.find((item) => item.id === timeframe)?.label ?? timeframe;
  const visiblePrice = livePrice && livePrice > 0 ? livePrice : bollinger?.price ?? 0;
  const pressureCaption = bollinger
    ? `BTCUSDT · ${timeframeLabel} · BOLLINGER ${scoreNumber.format(targetScore)}%${visiblePrice > 0 ? ` · $${money.format(visiblePrice)}` : ""}`
    : pressureError ? "BTC BOLLINGER TIJDELIJK ONBESCHIKBAAR" : "BTC BOLLINGER";
  const impactPosition = 50 + (displayLongShare - 50) * 0.10;
  const visualIntensity = Math.min(1, 0.28 + Math.abs(displayLongShare - 50) / 50 * 1.18);
  const visualStyle = { "--long-share": `${displayLongShare}%`, "--impact-x": `${impactPosition}%`, "--battle-intensity": visualIntensity } as React.CSSProperties;
  const videoReady = forwardReady && (!reverseFailed ? reverseReady : true);
  const videoFailed = forwardFailed;

  return <div className={styles.module}>
    <div className={styles.timeframes} role="group" aria-label="BTC Bollinger timeframe">
      {TIMEFRAMES.map((item) => <button key={item.id} type="button" className={item.id === timeframe ? styles.activeTimeframe : ""} aria-pressed={item.id === timeframe} onClick={() => setTimeframe(item.id)}>{item.label}</button>)}
    </div>

    <section className={`${styles.card} ${!dataAvailable ? styles.unavailable : ""}`} style={visualStyle}
      data-bollinger-score={targetScore.toFixed(3)} data-visual-long-share={displayLongShare.toFixed(3)} data-target-long-share={targetScore.toFixed(3)}
      data-timeframe={timeframe} data-updated-at={livePriceAt ?? bollinger?.updatedAt ?? updatedAt ?? ""} data-video-ready={videoReady ? "true" : "false"} data-video-failed={videoFailed ? "true" : "false"}
      data-market-live={marketConnected ? "true" : "false"} data-playback-direction={activeDirection}
      aria-label={`Portfolio impact. Long open P&L ${formatUsd(snapshot.longPnl, true)}, short open P&L ${formatUsd(snapshot.shortPnl, true)}, netto ${formatUsd(netPnl, true)}. BTC Bollinger ${scoreNumber.format(targetScore)} procent. ${pressureStatus}.`}>
      <img className={videoStyles.poster} src={POSTER_SOURCE} alt="" aria-hidden="true" />
      {!forwardFailed ? <>
        <video ref={forwardVideoRef} className={`${videoStyles.video} ${forwardReady ? videoStyles.videoReady : ""} ${activeDirection === "forward" ? videoStyles.videoActive : videoStyles.videoInactive}`} src={MASTER_SOURCE} poster={POSTER_SOURCE}
          preload="auto" muted playsInline disablePictureInPicture aria-hidden="true" tabIndex={-1}
          onLoadedMetadata={() => syncVideoAtCurrentScore("forward")}
          onCanPlay={() => { setForwardFailed(false); setForwardReady(true); }}
          onError={() => { setForwardFailed(true); setForwardReady(false); }} />
        {!reverseFailed ? <video ref={reverseVideoRef} className={`${videoStyles.video} ${reverseReady ? videoStyles.videoReady : ""} ${activeDirection === "reverse" ? videoStyles.videoActive : videoStyles.videoInactive}`} src={REVERSE_SOURCE} poster={POSTER_SOURCE}
          preload="auto" muted playsInline disablePictureInPicture aria-hidden="true" tabIndex={-1}
          onLoadedMetadata={() => syncVideoAtCurrentScore("reverse")}
          onCanPlay={() => { setReverseFailed(false); setReverseReady(true); }}
          onError={() => { setReverseFailed(true); setReverseReady(false); }} /> : null}
      </> : null}
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
