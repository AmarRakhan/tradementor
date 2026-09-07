from __future__ import annotations

import base64
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

COMPONENT = r'''"use client";

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
'''

CSS = r'''.module{width:100%;margin:14px 0 18px}.timeframes{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:6px;margin:0 0 7px;padding:4px;border:1px solid rgba(218,173,66,.34);border-radius:13px;background:linear-gradient(180deg,rgba(12,12,9,.92),rgba(4,6,5,.96));box-shadow:inset 0 1px 0 rgba(255,226,150,.05)}.timeframes button{min-width:0;height:30px;padding:0 4px;border:1px solid transparent;border-radius:9px;background:transparent;color:rgba(236,228,205,.66);font:800 11px/1 system-ui,sans-serif;letter-spacing:.02em;cursor:pointer;transition:background .18s ease,border-color .18s ease,color .18s ease,box-shadow .18s ease}.timeframes button:hover{color:#f3dfae;border-color:rgba(216,168,58,.22)}.timeframes .activeTimeframe{color:#171006;background:linear-gradient(180deg,#f1cc6b,#c9952f);border-color:#f4d57d;box-shadow:0 0 16px rgba(225,176,61,.22),inset 0 1px 0 rgba(255,255,255,.45)}
.card{--gold:#d7a83f;--green:#45efa4;--red:#ff667f;--long-share:50%;position:relative;isolation:isolate;overflow:hidden;aspect-ratio:1.72/1;border:1px solid rgba(222,177,70,.72);border-radius:23px;background:#020806;box-shadow:0 20px 54px rgba(0,0,0,.48),0 0 26px rgba(205,157,48,.08),inset 0 1px 0 rgba(255,229,159,.14);color:#f8fbf8;font-variant-numeric:tabular-nums}.card:after{content:"";position:absolute;inset:1px;z-index:8;border-radius:22px;box-shadow:inset 0 0 32px rgba(226,178,65,.08);pointer-events:none}.scene{position:absolute;z-index:0;inset:0;width:100%;height:100%;object-fit:cover;object-position:center;image-rendering:auto;user-select:none;pointer-events:none}.vignette{position:absolute;z-index:1;inset:0;background:linear-gradient(180deg,rgba(0,5,3,.30) 0%,rgba(0,4,2,.02) 28%,rgba(0,4,2,.01) 70%,rgba(0,5,3,.30) 100%),linear-gradient(90deg,rgba(0,8,4,.17),transparent 19%,transparent 81%,rgba(10,0,2,.17));pointer-events:none}.impact{position:absolute;z-index:3;left:50%;top:49%;width:46px;height:46px;transform:translate(-50%,-50%);pointer-events:none}.impact:before{content:"";position:absolute;inset:14px;border-radius:50%;background:#ffd77b;box-shadow:0 0 9px #ffd26b,0 0 22px rgba(255,165,59,.58);animation:impactPulse 1.8s ease-in-out infinite}.impact i{position:absolute;left:50%;top:50%;width:1px;height:25px;border-radius:2px;background:linear-gradient(#fff6ce,#ffc45d,transparent);transform-origin:50% 0;opacity:.8}.impact i:nth-child(1){transform:rotate(28deg) translateY(-6px)}.impact i:nth-child(2){transform:rotate(148deg) translateY(-6px)}.impact i:nth-child(3){transform:rotate(268deg) translateY(-6px)}
.sidePanel{position:absolute;z-index:4;top:48px;width:21%;min-width:104px;max-width:158px;padding:8px 9px 8px;border:1px solid;border-radius:14px;background:rgba(4,12,8,.70);box-shadow:inset 0 1px 0 rgba(255,255,255,.035),0 8px 22px rgba(0,0,0,.20)}.longPanel{left:15px;border-color:rgba(54,224,143,.48);background:linear-gradient(145deg,rgba(1,30,19,.74),rgba(2,12,8,.48))}.shortPanel{right:15px;text-align:right;border-color:rgba(255,80,106,.50);background:linear-gradient(215deg,rgba(42,5,12,.75),rgba(17,3,6,.48))}.sideTitle{display:flex;align-items:center;gap:6px;margin-bottom:6px;font-size:14px;font-weight:900;letter-spacing:.07em}.longPanel .sideTitle{color:var(--green)}.shortPanel .sideTitle{justify-content:flex-end;color:var(--red)}.sideTitle i{font-style:normal;font-size:17px;line-height:1}.sidePanel small{display:block;color:rgba(236,242,238,.78);font-size:9px;line-height:1.2}.sidePanel>strong{display:block;margin-top:2px;font-size:18px;line-height:1.06;letter-spacing:-.035em}.sidePanel em{display:block;margin-top:2px;font-size:10px;font-style:normal;font-weight:800}.positionCount{display:block;margin-top:6px;color:rgba(248,250,248,.84);font-size:10px;font-weight:750}.centerPanel{position:absolute;z-index:5;top:10px;left:50%;width:42%;max-width:320px;transform:translateX(-50%);padding:5px 9px 9px;text-align:center;border-radius:15px;background:linear-gradient(180deg,rgba(2,9,6,.83),rgba(2,8,5,.28) 70%,transparent);text-shadow:0 3px 14px rgba(0,0,0,.95)}.centerTitle{display:flex;align-items:center;justify-content:center;gap:7px;color:#e8bf5f;font-size:11px;font-weight:900;letter-spacing:.10em}.centerTitle i{width:6px;height:6px;border-radius:50%;background:#f2c356;box-shadow:0 0 11px rgba(242,195,86,.8);animation:livePulse 2s ease-in-out infinite}.centerPanel>strong{display:block;margin-top:4px;font-size:clamp(25px,4.5vw,39px);line-height:1;font-weight:900;letter-spacing:-.04em}.centerPanel>span{display:block;margin-top:3px;font-size:12px;font-weight:850}.positive{color:#49e7a0!important;text-shadow:0 0 16px rgba(54,232,153,.18)}.negative{color:#ff667f!important;text-shadow:0 0 16px rgba(255,75,105,.18)}.neutral{color:#f3e2bb!important}.battleFooter{position:absolute;z-index:5;left:15px;right:15px;bottom:8px;padding-top:19px;background:linear-gradient(180deg,transparent,rgba(2,8,5,.22) 36%,rgba(2,8,5,.66) 100%)}.status{text-align:center;color:#f5ead0;font-size:12px;font-weight:950;letter-spacing:.055em;text-shadow:0 2px 12px #000,0 0 12px rgba(223,176,71,.18)}.balanceRow{display:grid;grid-template-columns:62px 1fr 62px;align-items:center;gap:9px;margin-top:7px}.share strong{display:block;font-size:20px;line-height:1;font-weight:950}.longShare{text-align:right;color:var(--green)}.shortShare{text-align:left;color:var(--red)}.balanceTrack{position:relative;height:16px;border:1px solid rgba(220,176,75,.36);border-radius:999px;background:rgba(0,0,0,.58);box-shadow:inset 0 2px 8px rgba(0,0,0,.74),0 0 19px rgba(215,164,57,.10);overflow:hidden}.longFill,.shortFill{position:absolute;top:2px;bottom:2px;transition:width .45s cubic-bezier(.2,.8,.2,1)}.longFill{left:2px;width:calc(var(--long-share) - 2px);border-radius:999px 3px 3px 999px;background:linear-gradient(90deg,#18c878,#69f5ac);box-shadow:0 0 14px rgba(57,234,150,.36)}.shortFill{right:2px;width:calc(100% - var(--long-share) - 2px);border-radius:3px 999px 999px 3px;background:linear-gradient(90deg,#d63f58,#ff6a82);box-shadow:0 0 14px rgba(255,76,105,.34)}.balanceTrack>i{position:absolute;z-index:2;top:-4px;bottom:-4px;left:var(--long-share);width:2px;transform:translateX(-1px);background:#fff0b5;box-shadow:0 0 9px #f4a43d,0 0 15px rgba(255,167,57,.6);transition:left .45s cubic-bezier(.2,.8,.2,1)}.barCaption{margin-top:5px;text-align:center;color:rgba(238,229,205,.72);font-size:8px;font-weight:850;letter-spacing:.10em}.loadingCopy{position:absolute;z-index:5;left:50%;top:35%;width:min(78%,440px);transform:translate(-50%,-50%);text-align:center;padding:14px;border:1px solid rgba(219,175,70,.24);border-radius:15px;background:rgba(3,10,7,.70)}.loadingCopy span{display:block;color:#deb75d;font-size:11px;font-weight:900;letter-spacing:.12em}.loadingCopy strong{display:block;margin-top:7px;font-size:18px}.loadingCopy small{display:block;margin-top:4px;color:rgba(236,241,237,.66)}
@keyframes impactPulse{0%,100%{opacity:.72;transform:scale(.88)}50%{opacity:1;transform:scale(1.12)}}@keyframes livePulse{0%,100%{opacity:.56;transform:scale(.82)}50%{opacity:1;transform:scale(1.14)}}
@media(max-width:700px){.module{margin:11px 0 14px}.timeframes{gap:4px;padding:3px;margin-bottom:6px;border-radius:11px}.timeframes button{height:27px;padding:0 2px;border-radius:8px;font-size:10px}.card{aspect-ratio:1.62/1;border-radius:19px}.sidePanel{top:40px;width:21.5%;min-width:0;padding:6px 6px 6px;border-radius:11px}.longPanel{left:9px}.shortPanel{right:9px}.sideTitle{font-size:10px;gap:3px;margin-bottom:4px}.sideTitle i{font-size:12px}.sidePanel small{font-size:7px}.sidePanel>strong{font-size:12px;white-space:nowrap}.sidePanel em{font-size:7.5px}.positionCount{margin-top:4px;font-size:7.5px}.centerPanel{top:7px;width:45%;padding:4px 5px 6px}.centerTitle{font-size:7.2px;letter-spacing:.06em}.centerTitle i{width:4px;height:4px}.centerPanel>strong{font-size:20px;white-space:nowrap}.centerPanel>span{font-size:8px}.impact{top:49%;width:36px;height:36px}.impact:before{inset:11px}.battleFooter{left:9px;right:9px;bottom:6px;padding-top:15px}.status{font-size:8.8px;letter-spacing:.025em}.balanceRow{grid-template-columns:42px 1fr 42px;gap:6px;margin-top:5px}.share strong{font-size:14px}.balanceTrack{height:11px}.longFill,.shortFill{top:1px;bottom:1px}.barCaption{margin-top:4px;font-size:5.8px;letter-spacing:.065em;white-space:nowrap}.loadingCopy{top:38%;padding:10px}.loadingCopy strong{font-size:15px}.loadingCopy small{font-size:9px}}
@media(max-width:380px){.timeframes button{font-size:9.4px}.card{aspect-ratio:1.57/1}.sidePanel{width:22%;padding-inline:5px}.sidePanel>strong{font-size:11.5px}.centerPanel{width:44%}.centerPanel>strong{font-size:18.5px}.centerTitle{font-size:6.8px}.status{font-size:8.1px}.balanceRow{grid-template-columns:39px 1fr 39px}.share strong{font-size:13px}.barCaption{font-size:5.3px}}
@media(prefers-reduced-motion:reduce){.impact:before,.centerTitle i{animation:none!important}.timeframes button,.longFill,.shortFill,.balanceTrack>i{transition:none!important}}
'''

LIB = r'''const EPSILON = 1e-9;

function finite(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function readNumber(record, keys) {
  if (!record || typeof record !== "object") return null;
  for (const key of keys) {
    const value = finite(record[key]);
    if (value !== null) return value;
  }
  return null;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

export function positionExposure(position) {
  if (!position || typeof position !== "object") return 0;
  const direct = readNumber(position, ["notional", "notionalUsd", "notionalUSDT", "positionNotional", "exposure", "exposureUsd"]);
  if (direct !== null && direct !== 0) return Math.abs(direct);
  const size = readNumber(position, ["size", "qty", "quantity", "positionAmt"]);
  const mark = readNumber(position, ["markPrice", "price", "entry", "entryPrice"]);
  if (size !== null && mark !== null) return Math.abs(size * mark);
  const margin = readNumber(position, ["margin", "marginUsd", "initialMargin", "positionInitialMargin"]);
  const leverage = readNumber(position, ["leverage"]);
  if (margin !== null && leverage !== null) return Math.abs(margin * leverage);
  return Math.abs(margin ?? 0);
}

export function dominancePresentation(score = 0) {
  const normalized = clamp(finite(score) ?? 0, -100, 100);
  const roundedScore = Math.round(normalized);
  const longShare = Math.round(clamp(50 + normalized * 0.46, 4, 96));
  const shortShare = 100 - longShare;
  const stateIndex = Math.round(clamp((normalized + 100) / 12.5, 0, 16));
  let status = "IN EVENWICHT";
  if (normalized >= 70) status = "LONGS DOMINEREN";
  else if (normalized >= 35) status = "LONGS DRUKKEN HARDER";
  else if (normalized >= 12) status = "LONGS DRUKKEN LICHT HARDER";
  else if (normalized <= -70) status = "SHORTS DOMINEREN";
  else if (normalized <= -35) status = "SHORTS DRUKKEN HARDER";
  else if (normalized <= -12) status = "SHORTS DRUKKEN LICHT HARDER";
  return { score: roundedScore, longShare, shortShare, stateIndex, status, barLabel: "MARKTDRUK" };
}

function livePressure(longDelta, shortDelta, longExposure, shortExposure, equityBasis) {
  const longBasis = Math.max(Math.abs(longExposure), 1);
  const shortBasis = Math.max(Math.abs(shortExposure), 1);
  const longRate = longDelta / longBasis;
  const shortRate = shortDelta / shortBasis;
  const absoluteMovement = Math.abs(longDelta) + Math.abs(shortDelta);
  const dollarNoiseFloor = Math.max(0.02, equityBasis * 0.00025);
  if (absoluteMovement <= dollarNoiseFloor) return { bias: 0, longShare: 50 };
  const observedRateMovement = Math.abs(longRate) + Math.abs(shortRate);
  if (observedRateMovement <= EPSILON) return { bias: 0, longShare: 50 };
  const edge = longRate - shortRate;
  const directionalEdge = clamp(edge / observedRateMovement, -1, 1);
  const confidence = clamp((absoluteMovement - dollarNoiseFloor) / Math.max(dollarNoiseFloor * 4, 0.05), 0, 1);
  const bias = clamp(Math.tanh(directionalEdge * 1.32) * confidence, -1, 1);
  const longShare = clamp(50 + bias * 42, 8, 92);
  return { bias, longShare };
}

export function deriveBattleMetrics({ longPnl = 0, shortPnl = 0, longDelta = 0, shortDelta = 0, longExposure = 0, shortExposure = 0, equity = 0, dominanceScore = null } = {}) {
  const netPnl = longPnl + shortPnl;
  const equityBasis = Math.max(Math.abs(equity), 100);
  const momentumWeight = 1.35;
  const longScore = longPnl + longDelta * momentumWeight;
  const shortScore = shortPnl + shortDelta * momentumWeight;
  const bothPositive = longPnl > 0 && shortPnl > 0;
  const bothNegative = longPnl < 0 && shortPnl < 0;
  const nearZero = Math.abs(longPnl) + Math.abs(shortPnl) < Math.max(0.05, equityBasis * 0.00001);
  const state = nearZero ? "BALANCED" : bothPositive ? "BOTH_POSITIVE" : bothNegative ? "BOTH_NEGATIVE" : longPnl >= 0 ? "LONG_DOMINANT" : "SHORT_DOMINANT";

  if (finite(dominanceScore) !== null) {
    const market = dominancePresentation(dominanceScore);
    return {
      netPnl,
      longScore,
      shortScore,
      longShare: market.longShare,
      shortShare: market.shortShare,
      motionBias: market.score / 100,
      intensity: clamp(Math.abs(market.score) / 100, 0.18, 1),
      state,
      status: market.status,
      barLabel: market.barLabel,
      dominanceScore: market.score,
      stateIndex: market.stateIndex,
    };
  }

  const pressure = livePressure(longDelta, shortDelta, longExposure, shortExposure, equityBasis);
  const motionBias = pressure.bias;
  const roundedLongShare = Math.round(pressure.longShare);
  const shortShare = 100 - roundedLongShare;
  let status = "IN EVENWICHT";
  if (motionBias >= 0.12) status = "LONGS DRUKKEN HARDER";
  else if (motionBias <= -0.12) status = "SHORTS DRUKKEN HARDER";
  const normalizedLongMove = Math.abs(longDelta) / Math.max(Math.abs(longExposure), equityBasis, 1);
  const normalizedShortMove = Math.abs(shortDelta) / Math.max(Math.abs(shortExposure), equityBasis, 1);
  const intensity = clamp((normalizedLongMove + normalizedShortMove) / 0.0006, 0.18, 1);
  return {
    netPnl,
    longScore,
    shortScore,
    longShare: roundedLongShare,
    shortShare,
    motionBias,
    intensity,
    state,
    status,
    barLabel: "LIVE DRUK",
  };
}
'''

DTS = r'''export type DominancePresentation = {
  score: number;
  longShare: number;
  shortShare: number;
  stateIndex: number;
  status: string;
  barLabel: string;
};
export type PortfolioBattleMetrics = {
  netPnl: number;
  longScore: number;
  shortScore: number;
  longShare: number;
  shortShare: number;
  motionBias: number;
  intensity: number;
  state: string;
  status: string;
  barLabel: string;
  dominanceScore?: number;
  stateIndex?: number;
};
export function positionExposure(position: unknown): number;
export function dominancePresentation(score?: number): DominancePresentation;
export function deriveBattleMetrics(input?: {
  longPnl?: number;
  shortPnl?: number;
  longDelta?: number;
  shortDelta?: number;
  longExposure?: number;
  shortExposure?: number;
  equity?: number;
  dominanceScore?: number | null;
}): PortfolioBattleMetrics;
'''

ROUTE = r'''import { dominancePresentation } from "@/lib/portfolio-impact-battle.mjs";

const ASTER = "https://fapi.asterdex.com";
const MAX_SYMBOLS = 16;
const FETCH_TIMEOUT_MS = 8_000;
const DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT"];

type Timeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "24h";
type FrameConfig = { interval: string; windowMs: number; limit: number; scalePct: number; ttlMs: number };
type Candle = { openTime: number; closeTime: number; open: number; high: number; low: number; close: number };
type SymbolPressure = { symbol: string; score: number; returnPct: number; price: number; candles: number; momentum: number; trend: number };
type CacheEntry = { expiresAt: number; value: Record<string, unknown> };

const FRAMES: Record<Timeframe, FrameConfig> = {
  "1m": { interval: "1m", windowMs: 60_000, limit: 4, scalePct: 0.16, ttlMs: 12_000 },
  "5m": { interval: "1m", windowMs: 5 * 60_000, limit: 7, scalePct: 0.34, ttlMs: 20_000 },
  "15m": { interval: "1m", windowMs: 15 * 60_000, limit: 17, scalePct: 0.65, ttlMs: 35_000 },
  "1h": { interval: "5m", windowMs: 60 * 60_000, limit: 14, scalePct: 1.15, ttlMs: 60_000 },
  "4h": { interval: "15m", windowMs: 4 * 60 * 60_000, limit: 18, scalePct: 2.10, ttlMs: 120_000 },
  "24h": { interval: "1h", windowMs: 24 * 60 * 60_000, limit: 26, scalePct: 4.25, ttlMs: 300_000 },
};
const cache = new Map<string, CacheEntry>();

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}
function finite(value: unknown) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}
function parseSymbols(raw: string) {
  const requested = raw.split(",").map((value) => value.trim().toUpperCase().replace(/[\/_-]/g, "")).filter(Boolean);
  if (requested.some((symbol) => !/^[A-Z0-9]+USDT$/.test(symbol))) throw new Error("Ongeldig Aster-symbool in marktdruk-aanvraag");
  const unique = Array.from(new Set(requested));
  for (const symbol of DEFAULT_SYMBOLS) {
    if (unique.length >= 8) break;
    if (!unique.includes(symbol)) unique.push(symbol);
  }
  return unique.slice(0, MAX_SYMBOLS);
}

async function jsonFetch(url: string) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(url, { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error(`Aster candles HTTP ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

function parseCandles(payload: unknown): Candle[] {
  if (!Array.isArray(payload)) return [];
  return payload.map((row) => {
    if (!Array.isArray(row)) return null;
    const candle = {
      openTime: finite(row[0]),
      open: finite(row[1]),
      high: finite(row[2]),
      low: finite(row[3]),
      close: finite(row[4]),
      closeTime: finite(row[6]) || finite(row[0]),
    };
    return candle.open > 0 && candle.high > 0 && candle.low > 0 && candle.close > 0 ? candle : null;
  }).filter((row): row is Candle => Boolean(row));
}

function regressionTrendPct(candles: Candle[]) {
  if (candles.length < 2) return 0;
  const n = candles.length;
  const meanX = (n - 1) / 2;
  const meanY = candles.reduce((sum, candle) => sum + candle.close, 0) / n;
  let numerator = 0;
  let denominator = 0;
  for (let i = 0; i < n; i += 1) {
    numerator += (i - meanX) * (candles[i].close - meanY);
    denominator += (i - meanX) ** 2;
  }
  if (denominator <= 0 || meanY <= 0) return 0;
  const slope = numerator / denominator;
  return slope * (n - 1) / meanY * 100;
}

function analyze(symbol: string, candles: Candle[], config: FrameConfig): SymbolPressure | null {
  if (candles.length < 2) return null;
  const last = candles.at(-1)!;
  const targetTime = last.closeTime - config.windowMs;
  let anchor = candles[0];
  for (const candle of candles) {
    if (candle.openTime <= targetTime) anchor = candle;
    else break;
  }
  const windowCandles = candles.filter((candle) => candle.closeTime > targetTime);
  if (!windowCandles.length || anchor.open <= 0) return null;
  const returnPct = (last.close - anchor.open) / anchor.open * 100;
  const price = Math.tanh(returnPct / config.scalePct) * 100;
  const body = windowCandles.reduce((sum, candle) => {
    const range = Math.max(candle.high - candle.low, candle.open * 0.000001);
    return sum + clamp((candle.close - candle.open) / range, -1, 1);
  }, 0) / windowCandles.length * 100;
  const momentumAnchor = windowCandles[Math.max(0, windowCandles.length - Math.min(4, windowCandles.length))];
  const recentPct = momentumAnchor.close > 0 ? (last.close - momentumAnchor.close) / momentumAnchor.close * 100 : 0;
  const momentum = Math.tanh(recentPct / Math.max(config.scalePct * 0.46, 0.04)) * 100;
  const trendPct = regressionTrendPct(windowCandles);
  const trend = Math.tanh(trendPct / Math.max(config.scalePct, 0.05)) * 100;
  const score = clamp(price * 0.42 + body * 0.18 + momentum * 0.22 + trend * 0.18, -100, 100);
  return { symbol, score, returnPct, price, candles: body, momentum, trend };
}

async function symbolPressure(symbol: string, config: FrameConfig) {
  const url = new URL(`${ASTER}/fapi/v1/klines`);
  url.searchParams.set("symbol", symbol);
  url.searchParams.set("interval", config.interval);
  url.searchParams.set("limit", String(config.limit));
  const candles = parseCandles(await jsonFetch(url.toString()));
  return analyze(symbol, candles, config);
}

async function mapLimit<T, R>(items: T[], limit: number, worker: (item: T) => Promise<R>): Promise<R[]> {
  const output = new Array<R>(items.length);
  let cursor = 0;
  const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (true) {
      const index = cursor;
      cursor += 1;
      if (index >= items.length) return;
      output[index] = await worker(items[index]);
    }
  });
  await Promise.all(runners);
  return output;
}

export async function GET(request: Request) {
  const authorization = request.headers.get("authorization") || "";
  if (!authorization.startsWith("Bearer ")) return Response.json({ detail: "Firebase ID-token ontbreekt" }, { status: 401 });
  const url = new URL(request.url);
  const timeframe = (url.searchParams.get("timeframe") || "15m") as Timeframe;
  const config = FRAMES[timeframe];
  if (!config) return Response.json({ detail: "Ongeldig Portfolio Impact-timeframe" }, { status: 422 });

  try {
    const symbols = parseSymbols(url.searchParams.get("symbols") || "");
    const cacheKey = `${timeframe}|${[...symbols].sort().join(",")}`;
    const cached = cache.get(cacheKey);
    if (cached && cached.expiresAt > Date.now()) return Response.json(cached.value, { headers: { "Cache-Control": "private, no-store" } });

    const settled = await mapLimit(symbols, 4, async (symbol) => {
      try { return await symbolPressure(symbol, config); }
      catch { return null; }
    });
    const rows = settled.filter((row): row is SymbolPressure => Boolean(row));
    if (rows.length < 3) throw new Error("Onvoldoende realtime Aster-candles voor een betrouwbare marktdrukscore");

    const average = (key: keyof Pick<SymbolPressure, "score" | "price" | "candles" | "momentum" | "trend">) => rows.reduce((sum, row) => sum + row[key], 0) / rows.length;
    const up = rows.filter((row) => row.returnPct > 0.002).length;
    const down = rows.filter((row) => row.returnPct < -0.002).length;
    const flat = rows.length - up - down;
    const breadth = (up - down) / rows.length * 100;
    const aggregateScore = clamp(average("score") * 0.82 + breadth * 0.18, -100, 100);
    const presentation = dominancePresentation(aggregateScore);
    const value = {
      timeframe,
      score: presentation.score,
      longShare: presentation.longShare,
      shortShare: presentation.shortShare,
      stateIndex: presentation.stateIndex,
      status: presentation.status,
      barLabel: presentation.barLabel,
      symbolsUsed: rows.map((row) => row.symbol),
      breadth: { up, down, flat },
      components: {
        price: Math.round(average("price")),
        candles: Math.round(average("candles")),
        momentum: Math.round(average("momentum")),
        trend: Math.round(average("trend")),
        breadth: Math.round(breadth),
      },
      deterministic: true,
      readOnly: true,
      updatedAt: Date.now(),
    };
    cache.set(cacheKey, { expiresAt: Date.now() + config.ttlMs, value });
    return Response.json(value, { headers: { "Cache-Control": "private, no-store" } });
  } catch (reason) {
    const detail = reason instanceof Error ? reason.message : "Portfolio Impact-marktdruk kon niet worden berekend";
    return Response.json({ detail }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
'''

VISUAL_MAIN = r'''import React from "react";
import { createRoot } from "react-dom/client";
import { PortfolioImpactBattle } from "../../components/portfolio-impact-battle";

function positions(longPnl: number, shortPnl: number) {
  const longs = Array.from({ length: 25 }, (_, index) => ({ side: "long", symbol: `${["BTC", "ETH", "SOL", "BNB", "XRP"][index % 5]}USDT`, pnl: longPnl / 25, notional: 3482.15 / 25 }));
  const shorts = Array.from({ length: 19 }, (_, index) => ({ side: "short", symbol: `${["BTC", "ETH", "SOL", "BNB", "XRP"][index % 5]}USDT`, pnl: shortPnl / 19, notional: 5271.40 / 19 }));
  return [...longs, ...shorts];
}

const pressure = {
  "1m": -82,
  "5m": -64,
  "15m": -42,
  "1h": 2,
  "4h": 38,
  "24h": 78,
} as const;

function Fixture() {
  return <PortfolioImpactBattle positions={positions(-20.55, -147.92)} equity={41278.62} dataAvailable updatedAt={Date.now()} marketPressureOverride={pressure} />;
}

createRoot(document.getElementById("root")!).render(<main className="qa-shell"><Fixture /></main>);
'''

VISUAL_SCREENSHOTS = r'''import { chromium, webkit } from 'playwright';
import { mkdir } from 'node:fs/promises';
import assert from 'node:assert/strict';

await mkdir('artifacts/portfolio-impact', { recursive: true });
const url = 'http://127.0.0.1:4173/tests/visual/portfolio-impact.html';
const cases = [
  ['chromium-360', chromium, 360, 800],
  ['chromium-390', chromium, 390, 844],
  ['chromium-412', chromium, 412, 915],
  ['chromium-430', chromium, 430, 932],
  ['webkit-390', webkit, 390, 844],
];
for (const [name, type, width, height] of cases) {
  const browser = await type.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  await page.goto(url, { waitUntil: 'networkidle' });
  const card = page.locator('section[aria-label^="Portfolio impact."]');
  await card.waitFor({ state: 'visible' });
  const box = await card.boundingBox();
  assert.ok(box && box.width <= width, `${name}: card exceeds viewport width`);
  const ratio = box ? box.width / box.height : 0;
  assert.ok(box && box.height >= 195 && box.height <= 290, `${name}: card height ${box?.height ?? 'n/a'}px outside approved cinematic mobile target`);
  assert.ok(ratio >= 1.45 && ratio <= 1.90, `${name}: card ratio ${ratio.toFixed(2)} outside approved cinematic target`);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  assert.ok(overflow <= 0, `${name}: horizontal overflow ${overflow}px`);
  assert.match(await card.innerText(), /SHORTS DRUKKEN HARDER/, `${name}: 15m fixture must show short pressure`);
  const sceneSrc = await card.locator('img').first().getAttribute('src');
  assert.match(sceneSrc || '', /portfolio-impact-states\/state-0[0-9]\.svg/, `${name}: state-based scene asset missing`);
  await card.screenshot({ path: `artifacts/portfolio-impact/${name}.png` });
  await browser.close();
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' });
await page.goto(url, { waitUntil: 'networkidle' });
const card = page.locator('section[aria-label^="Portfolio impact."]');
await card.waitFor({ state: 'visible' });
for (const [label, expected] of [
  ['1m', 'SHORTS DOMINEREN'],
  ['5m', 'SHORTS DRUKKEN HARDER'],
  ['15m', 'SHORTS DRUKKEN HARDER'],
  ['1u', 'IN EVENWICHT'],
  ['4u', 'LONGS DRUKKEN HARDER'],
  ['24u', 'LONGS DOMINEREN'],
]) {
  await page.getByRole('button', { name: label, exact: true }).click();
  await page.waitForTimeout(40);
  assert.match(await card.innerText(), new RegExp(expected), `${label}: expected ${expected}`);
}
const reducedBox = await card.boundingBox();
assert.ok(reducedBox && reducedBox.height >= 195 && reducedBox.height <= 290, 'reduced-motion-390: cinematic card geometry regressed');
await card.screenshot({ path: 'artifacts/portfolio-impact/reduced-motion-390.png' });
await browser.close();
console.log('Portfolio Impact timeframe/state visual QA complete');
'''

TEST = r'''import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dominancePresentation, deriveBattleMetrics } from "../lib/portfolio-impact-battle.mjs";

const component = readFileSync(new URL("../components/portfolio-impact-battle.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../components/portfolio-impact-battle.module.css", import.meta.url), "utf8");
const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
const route = readFileSync(new URL("../app/api/markets/aster/pressure/route.ts", import.meta.url), "utf8");

test("dominance score maps deterministically to pressure, status and one of 17 states", () => {
  assert.deepEqual(dominancePresentation(0), { score: 0, longShare: 50, shortShare: 50, stateIndex: 8, status: "IN EVENWICHT", barLabel: "MARKTDRUK" });
  assert.equal(dominancePresentation(82).status, "LONGS DOMINEREN");
  assert.equal(dominancePresentation(-82).status, "SHORTS DOMINEREN");
  assert.ok(dominancePresentation(100).stateIndex === 16);
  assert.ok(dominancePresentation(-100).stateIndex === 0);
  assert.ok(dominancePresentation(38).longShare > 50);
  assert.ok(dominancePresentation(-38).shortShare > 50);
});

test("legacy battle helper remains backward-compatible while market score can drive it explicitly", () => {
  const legacy = deriveBattleMetrics({ longPnl: -40, shortPnl: -120, longDelta: 8, shortDelta: -7, longExposure: 5000, shortExposure: 5000, equity: 10000 });
  assert.equal(legacy.status, "LONGS DRUKKEN HARDER");
  const market = deriveBattleMetrics({ longPnl: -40, shortPnl: -120, equity: 10000, dominanceScore: -78 });
  assert.equal(market.status, "SHORTS DOMINEREN");
  assert.equal(market.barLabel, "MARKTDRUK");
});

test("all six requested timeframes are functional controls and Exposure is absent from visible side panels", () => {
  for (const token of ['id: "1m"', 'id: "5m"', 'id: "15m"', 'id: "1h"', 'id: "4h"', 'id: "24h"']) assert.match(component, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.match(component, /label: "1u"/);
  assert.match(component, /label: "4u"/);
  assert.doesNotMatch(component, />Exposure</);
  assert.match(component, /Open P&amp;L/);
  assert.match(component, /positionCount/);
});

test("state-based visual engine ships 17 precomposed assets and does not filter or animate the bull scene", () => {
  const assets = readdirSync(new URL("../public/portfolio-impact-states/", import.meta.url)).filter((name) => /^state-\d\d\.svg$/.test(name));
  assert.equal(assets.length, 17);
  assert.match(component, /portfolio-impact-states\/state-/);
  const sceneRule = css.match(/\.scene\{[^}]+\}/)?.[0] || "";
  assert.doesNotMatch(sceneRule, /filter:/);
  assert.doesNotMatch(sceneRule, /animation:/);
});

test("Aster page places Bulls after account metrics and directly before Tradecentrum component", () => {
  const metrics = page.indexOf('label="PORTFOLIOWAARDE"');
  const bulls = page.indexOf('destination === "aster" && <PortfolioImpactBattle');
  const tradeCenter = page.indexOf('destination === "aster" && <AsterRecentTrades');
  assert.ok(metrics >= 0 && bulls > metrics, "Bulls must be below portfolio/account metrics");
  assert.ok(tradeCenter > bulls, "Bulls must be immediately before Aster Tradecentrum");
  const between = page.slice(bulls, tradeCenter);
  assert.doesNotMatch(between, /<section className=/, "No other main section may sit between Bulls and Tradecentrum");
});

test("market-pressure route is read-only, deterministic and based on candles rather than account Open P&L", () => {
  assert.match(route, /export async function GET/);
  assert.match(route, /deterministic: true/);
  assert.match(route, /readOnly: true/);
  assert.match(route, /fapi\/v1\/klines/);
  assert.match(route, /price \* 0\.42/);
  assert.match(route, /body \* 0\.18/);
  assert.match(route, /momentum \* 0\.22/);
  assert.match(route, /trend \* 0\.18/);
  assert.doesNotMatch(route, /POST|close-all|strategy2\/start|strategy2\/stop|positions\/.*close/);
});
'''


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip(), encoding="utf-8")


def generate_states() -> None:
    artwork = WEB / "public" / "portfolio-impact-bulls.webp"
    if not artwork.exists():
        raise SystemExit("Missing web/public/portfolio-impact-bulls.webp")
    encoded = base64.b64encode(artwork.read_bytes()).decode("ascii")
    out = WEB / "public" / "portfolio-impact-states"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("state-*.svg"):
        old.unlink()
    rocks = "".join([
        '<path d="M0 273 L52 255 L108 267 L166 250 L224 269 L286 252 L352 271 L420 251 L488 269 L552 250 L618 268 L680 253 L720 264 L720 303 L0 303 Z" fill="#111813" opacity=".72"/>',
        '<path d="M0 286 L64 270 L116 281 L180 264 L244 284 L308 267 L372 283 L440 265 L506 282 L570 266 L636 282 L700 268 L720 274" fill="none" stroke="#475047" stroke-width="2" opacity=".32"/>',
        '<path d="M34 278 l18 -8 17 9 -15 10z M132 272 l19 -9 21 11 -18 11z M242 278 l20 -10 18 11 -15 10z M354 274 l20 -10 23 12 -20 11z M474 278 l18 -9 22 11 -18 10z M594 274 l20 -9 19 11 -16 10z" fill="#303831" opacity=".38"/>',
    ])
    for index in range(17):
        bias = (index - 8) / 8.0
        if bias >= 0:
            long_dx = round(34 * bias)
            short_dx = round(168 * bias)
            long_opacity = 1.0
            short_opacity = 1.0 - 0.16 * bias
            green_alpha = 0.20 + 0.12 * bias
            red_alpha = 0.20 - 0.08 * bias
        else:
            strength = -bias
            long_dx = -round(168 * strength)
            short_dx = -round(34 * strength)
            long_opacity = 1.0 - 0.16 * strength
            short_opacity = 1.0
            green_alpha = 0.20 - 0.08 * strength
            red_alpha = 0.20 + 0.12 * strength
        impact_x = round(360 + bias * 34)
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="606" viewBox="0 0 720 303" preserveAspectRatio="xMidYMid slice">
<defs>
  <linearGradient id="bg" x1="0" x2="1"><stop stop-color="#00140b"/><stop offset=".48" stop-color="#07100b"/><stop offset=".52" stop-color="#100807"/><stop offset="1" stop-color="#180007"/></linearGradient>
  <radialGradient id="green"><stop stop-color="#25ef95" stop-opacity=".42"/><stop offset="1" stop-color="#25ef95" stop-opacity="0"/></radialGradient>
  <radialGradient id="red"><stop stop-color="#ff4968" stop-opacity=".42"/><stop offset="1" stop-color="#ff4968" stop-opacity="0"/></radialGradient>
  <filter id="sparkGlow" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <image id="battle" width="720" height="303" href="data:image/webp;base64,{encoded}"/>
</defs>
<rect width="720" height="303" fill="url(#bg)"/>
<ellipse cx="132" cy="150" rx="235" ry="188" fill="url(#green)" opacity="{green_alpha:.3f}"/>
<ellipse cx="588" cy="150" rx="235" ry="188" fill="url(#red)" opacity="{red_alpha:.3f}"/>
<svg x="{long_dx}" y="0" width="360" height="303" viewBox="0 0 360 303" overflow="hidden" opacity="{long_opacity:.3f}"><use href="#battle"/></svg>
<svg x="{360 + short_dx}" y="0" width="360" height="303" viewBox="360 0 360 303" overflow="hidden" opacity="{short_opacity:.3f}"><use href="#battle"/></svg>
{rocks}
<g transform="translate({impact_x} 149)" filter="url(#sparkGlow)" opacity=".92">
  <circle r="3.2" fill="#fff0a9"/><circle r="8" fill="none" stroke="#f7b64e" stroke-opacity=".55"/>
  <path d="M-3 -5 L-17 -24 M4 -4 L21 -22 M-5 2 L-25 11 M5 3 L25 14 M0 6 L3 28" stroke="#ffd36e" stroke-width="1.4" stroke-linecap="round"/>
</g>
<rect x=".5" y=".5" width="719" height="302" rx="22" fill="none" stroke="#d9ac4c" stroke-opacity=".23"/>
</svg>'''
        (out / f"state-{index:02d}.svg").write_text(svg, encoding="utf-8")


def patch_page() -> None:
    path = WEB / "app" / "page.tsx"
    source = path.read_text(encoding="utf-8")
    old = '''      {!positionsOnly && (destination === "aster" ? <PortfolioImpactBattle
        positions={view.positions}
        equity={view.equityNumber}
        dataAvailable={view.accountDataAvailable}
        updatedAt={snapshot.updatedAt}
      /> : <section className="direction-balance" aria-label="Long en short balans">
        <DirectionBalanceCell label="LONG" count={view.accountDataAvailable ? longPositions.length : null} value={view.accountDataAvailable ? longPnl : null} />
        <DirectionBalanceCell label="NETTO OPEN PNL" value={view.accountDataAvailable ? netOpenPnl : null} center />
        <DirectionBalanceCell label="SHORT" count={view.accountDataAvailable ? shortPositions.length : null} value={view.accountDataAvailable ? shortPnl : null} />
      </section>)}'''
    new = '''      {!positionsOnly && destination !== "aster" && <section className="direction-balance" aria-label="Long en short balans">
        <DirectionBalanceCell label="LONG" count={view.accountDataAvailable ? longPositions.length : null} value={view.accountDataAvailable ? longPnl : null} />
        <DirectionBalanceCell label="NETTO OPEN PNL" value={view.accountDataAvailable ? netOpenPnl : null} center />
        <DirectionBalanceCell label="SHORT" count={view.accountDataAvailable ? shortPositions.length : null} value={view.accountDataAvailable ? shortPnl : null} />
      </section>}'''
    if old not in source:
        raise SystemExit("Could not locate current Bulls placement block in web/app/page.tsx")
    source = source.replace(old, new, 1)
    anchor = '      {!positionsOnly && destination === "aster" && <AsterRecentTrades snapshot={snapshot} onRetry={onRefresh} />}'
    insertion = '''      {!positionsOnly && destination === "aster" && <PortfolioImpactBattle
        positions={view.positions}
        equity={view.equityNumber}
        dataAvailable={view.accountDataAvailable}
        updatedAt={snapshot.updatedAt}
      />}

''' + anchor
    if anchor not in source:
        raise SystemExit("Could not locate Aster Tradecentrum anchor in web/app/page.tsx")
    source = source.replace(anchor, insertion, 1)
    path.write_text(source, encoding="utf-8")


write(WEB / "components" / "portfolio-impact-battle.tsx", COMPONENT)
write(WEB / "components" / "portfolio-impact-battle.module.css", CSS)
write(WEB / "lib" / "portfolio-impact-battle.mjs", LIB)
write(WEB / "lib" / "portfolio-impact-battle.d.ts", DTS)
write(WEB / "app" / "api" / "markets" / "aster" / "pressure" / "route.ts", ROUTE)
write(WEB / "tests" / "portfolio-impact-timeframes.test.mjs", TEST)
write(WEB / "tests" / "visual" / "portfolio-impact-main.tsx", VISUAL_MAIN)
write(WEB / "tests" / "visual" / "portfolio-impact-screenshots.mjs", VISUAL_SCREENSHOTS)
generate_states()
patch_page()
print("Portfolio Impact Bulls timeframe/state engine applied")
