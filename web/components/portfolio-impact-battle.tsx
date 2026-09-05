"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { deriveBattleMetrics, positionExposure, type PortfolioBattleMetrics } from "@/lib/portfolio-impact-battle.mjs";
import styles from "./portfolio-impact-battle.module.css";

type BattlePosition = Record<string, unknown>;
type Momentum = { long: number; short: number };
type HistoryPoint = { at: number; long: number; short: number };

type Props = {
  positions: unknown[];
  equity: number | null;
  dataAvailable: boolean;
  updatedAt?: number | null;
};

const money = new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const percent = new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const bullArtworkStyle = { backgroundImage: "url('/portfolio-impact-bulls.webp?v=4')" } as CSSProperties;

function numberFrom(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
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

function formatPercent(value: number) {
  if (!Number.isFinite(value)) return "—";
  const normalized = Math.abs(value) < 0.005 ? 0 : value;
  const sign = normalized > 0 ? "+" : normalized < 0 ? "-" : "";
  return `${sign}${percent.format(Math.abs(normalized))}%`;
}

function tone(value: number) {
  return value > 0.005 ? styles.positive : value < -0.005 ? styles.negative : styles.neutral;
}

export function PortfolioImpactBattle({ positions, equity, dataAvailable, updatedAt }: Props) {
  const history = useRef<HistoryPoint[]>([]);
  const lastSample = useRef<HistoryPoint | null>(null);
  const smoothedMomentum = useRef<Momentum>({ long: 0, short: 0 });
  const [momentum, setMomentum] = useState<Momentum>({ long: 0, short: 0 });

  const snapshot = useMemo(() => {
    const longs = positions.filter((position) => positionSide(position) === "long");
    const shorts = positions.filter((position) => positionSide(position) === "short");
    const longPnl = longs.reduce((total, position) => total + positionPnl(position), 0);
    const shortPnl = shorts.reduce((total, position) => total + positionPnl(position), 0);
    const longExposure = longs.reduce((total, position) => total + positionExposure(position), 0);
    const shortExposure = shorts.reduce((total, position) => total + positionExposure(position), 0);
    return { longs, shorts, longPnl, shortPnl, longExposure, shortExposure };
  }, [positions]);

  useEffect(() => {
    if (!dataAvailable) return;
    const now = Date.now();
    const point = { at: now, long: snapshot.longPnl, short: snapshot.shortPnl };
    const previous = lastSample.current;
    lastSample.current = point;

    const next = [...history.current, point].filter((sample) => now - sample.at <= 20_000);
    history.current = next;

    const target = now - 8_000;
    const anchor = next.reduce((best, sample) => Math.abs(sample.at - target) < Math.abs(best.at - target) ? sample : best, next[0]);
    const rollingReady = Boolean(anchor && now - anchor.at >= 1_250);
    const rolling = rollingReady
      ? { long: snapshot.longPnl - anchor.long, short: snapshot.shortPnl - anchor.short }
      : null;
    const instant = previous && now - previous.at <= 15_000
      ? { long: snapshot.longPnl - previous.long, short: snapshot.shortPnl - previous.short }
      : null;

    let raw: Momentum;
    if (rolling && instant) raw = { long: rolling.long * 0.72 + instant.long * 0.28, short: rolling.short * 0.72 + instant.short * 0.28 };
    else if (rolling) raw = rolling;
    else if (instant) raw = instant;
    else raw = smoothedMomentum.current;

    const moved = Math.abs(raw.long) + Math.abs(raw.short) > 0.0001;
    const alpha = moved ? 0.58 : 0.18;
    const previousSmooth = smoothedMomentum.current;
    const nextSmooth = {
      long: previousSmooth.long * (1 - alpha) + raw.long * alpha,
      short: previousSmooth.short * (1 - alpha) + raw.short * alpha,
    };
    smoothedMomentum.current = nextSmooth;
    setMomentum(nextSmooth);
  }, [snapshot.longPnl, snapshot.shortPnl, dataAvailable, updatedAt]);

  const metrics: PortfolioBattleMetrics = useMemo(() => deriveBattleMetrics({
    longPnl: snapshot.longPnl,
    shortPnl: snapshot.shortPnl,
    longDelta: momentum.long,
    shortDelta: momentum.short,
    longExposure: snapshot.longExposure,
    shortExposure: snapshot.shortExposure,
    equity: equity ?? 0,
  }), [snapshot, momentum, equity]);

  const netPercent = equity && Math.abs(equity) > 0.01 ? metrics.netPnl / Math.abs(equity) * 100 : 0;
  const equityBasis = equity && Math.abs(equity) > 0.01 ? Math.abs(equity) : 0;
  const longPercent = equityBasis ? snapshot.longPnl / equityBasis * 100 : 0;
  const shortPercent = equityBasis ? snapshot.shortPnl / equityBasis * 100 : 0;
  const visualStyle = {
    "--battle-bias": metrics.motionBias.toFixed(4),
    "--battle-intensity": metrics.intensity.toFixed(4),
    "--long-share": `${metrics.longShare}%`,
  } as CSSProperties;

  if (!dataAvailable) {
    return <section className={`${styles.card} ${styles.unavailable}`} aria-label="Portfolio impact wordt geladen">
      <div className={styles.loadingGlow} />
      <div className={styles.loadingCopy}><span>PORTFOLIO IMPACT</span><strong>Exchangegegevens laden…</strong><small>De laatste bevestigde Aster-posities worden opgehaald.</small></div>
    </section>;
  }

  return <section className={styles.card} style={visualStyle} data-state={metrics.state} aria-label={`Portfolio impact. Long open P&L ${formatUsd(snapshot.longPnl, true)}, short open P&L ${formatUsd(snapshot.shortPnl, true)}, netto ${formatUsd(metrics.netPnl, true)}. ${metrics.status}.`}>
    <div className={styles.cinematicBase} style={bullArtworkStyle} aria-hidden="true" />
    <div className={`${styles.bullLayer} ${styles.longBull}`} style={bullArtworkStyle} aria-hidden="true" />
    <div className={`${styles.bullLayer} ${styles.shortBull}`} style={bullArtworkStyle} aria-hidden="true" />
    <div className={styles.vignette} aria-hidden="true" />
    <div className={styles.smoke} aria-hidden="true" />
    <div className={styles.impact} aria-hidden="true"><i /><i /><i /></div>

    <div className={`${styles.sidePanel} ${styles.longPanel}`}>
      <div className={styles.sideTitle}><span>LONGS</span><i>↗</i></div>
      <small>Open P&amp;L</small>
      <strong className={tone(snapshot.longPnl)}>{formatUsd(snapshot.longPnl, true)}</strong>
      <em className={tone(snapshot.longPnl)}>{formatPercent(longPercent)}</em>
      <div className={styles.divider} />
      <small>Exposure</small>
      <b>{formatUsd(snapshot.longExposure)}</b>
      <span className={styles.positionCount}>{snapshot.longs.length} posities</span>
    </div>

    <div className={styles.centerPanel}>
      <div className={styles.centerTitle}><i />PORTFOLIO IMPACT</div>
      <strong className={tone(metrics.netPnl)}>{formatUsd(metrics.netPnl, true)}</strong>
      <span className={tone(metrics.netPnl)}>{formatPercent(netPercent)}</span>
    </div>

    <div className={`${styles.sidePanel} ${styles.shortPanel}`}>
      <div className={styles.sideTitle}><i>↙</i><span>SHORTS</span></div>
      <small>Open P&amp;L</small>
      <strong className={tone(snapshot.shortPnl)}>{formatUsd(snapshot.shortPnl, true)}</strong>
      <em className={tone(snapshot.shortPnl)}>{formatPercent(shortPercent)}</em>
      <div className={styles.divider} />
      <small>Exposure</small>
      <b>{formatUsd(snapshot.shortExposure)}</b>
      <span className={styles.positionCount}>{snapshot.shorts.length} posities</span>
    </div>

    <div className={styles.battleFooter}>
      <div className={styles.status}>{metrics.status}</div>
      <div className={styles.balanceRow}>
        <div className={`${styles.share} ${styles.longShare}`}><strong>{metrics.longShare}%</strong></div>
        <div className={styles.balanceTrack} aria-hidden="true"><div className={styles.longFill} /><div className={styles.shortFill} /><i /></div>
        <div className={`${styles.share} ${styles.shortShare}`}><strong>{metrics.shortShare}%</strong></div>
      </div>
      <div className={styles.barCaption}>{metrics.barLabel}</div>
    </div>
  </section>;
}
