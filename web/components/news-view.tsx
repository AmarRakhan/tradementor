"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import {
  TRADE_NEWS_FILTERS,
  TRADE_NEWS_TIMEFRAMES,
  accountPositions,
  activityEventsForItem,
  baseAsset,
  buildTradeNews,
  candleConfigForTimeframe,
  dcaUpdateFromEvents,
  filterTradeNews,
  finiteNumber,
  recoveryFromCandles,
  timeframeLabel,
  timestampMs,
  weightedAverageEntry,
} from "@/lib/trade-news.mjs";
import styles from "./news-view.module.css";

type Tone = "profit" | "loss" | "recovery" | "portfolio";
type NewsFilter = "all" | "wins" | "pressure" | "updates" | "portfolio";
type NewsTimeframe = "15m" | "1h" | "4h" | "today" | "24h" | "cycle";

type TradeEvent = {
  id?: string;
  kind?: string;
  dcaNumber?: number | null;
  symbol?: string;
  side?: string;
  price?: number | null;
  quantity?: number | null;
  notionalUsd?: number | null;
  at?: string;
  timestampMs?: number;
};

type Candle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
};

type NewsItem = {
  id: string;
  type: string;
  tone: Tone;
  filter: NewsFilter;
  priority: number;
  occurredAt: number;
  eyebrow: string;
  symbol: string;
  side: string;
  title: string;
  pnlUsd?: number | null;
  totalPnlUsd?: number | null;
  roiPct?: number | null;
  leverage?: number | null;
  dcaCount?: number | null;
  entryPrice?: number | null;
  averageEntry?: number | null;
  currentPrice?: number | null;
  exitPrice?: number | null;
  breakEvenPrice?: number | null;
  liquidationDistancePct?: number | null;
  feesUsd?: number | null;
  durationMs?: number | null;
  openedAt?: unknown;
  closedAt?: unknown;
  notionalUsd?: number | null;
  position?: Record<string, unknown> | null;
  source?: Record<string, unknown>;
};

type DetailState = {
  item: NewsItem;
  events: TradeEvent[];
  candles: Candle[];
  loading: boolean;
  error: string;
};

const EMPTY: Record<string, unknown> = {};

function number(value: unknown) {
  return finiteNumber(value) as number | null;
}

function money(value: unknown, signed = false) {
  const n = number(value);
  if (n === null) return "—";
  const abs = Math.abs(n);
  const digits = abs > 0 && abs < 0.01 ? 4 : 2;
  const formatted = new Intl.NumberFormat("nl-NL", {
    minimumFractionDigits: 2,
    maximumFractionDigits: digits,
  }).format(Math.abs(n));
  const prefix = n < 0 ? "-" : signed && n > 0 ? "+" : "";
  return `${prefix}$${formatted}`;
}

function percent(value: unknown, signed = false) {
  const n = number(value);
  if (n === null) return "—";
  const prefix = n < 0 ? "-" : signed && n > 0 ? "+" : "";
  return `${prefix}${Math.abs(n).toFixed(2).replace(".", ",")}%`;
}

function price(value: unknown) {
  const n = number(value);
  if (n === null || n <= 0) return "—";
  const decimals = n < 1 ? 6 : n < 100 ? 4 : 2;
  return `$${new Intl.NumberFormat("nl-NL", {
    minimumFractionDigits: n < 1 ? 4 : 2,
    maximumFractionDigits: decimals,
  }).format(n)}`;
}

function duration(value: unknown) {
  const ms = number(value);
  if (ms === null || ms <= 0) return "—";
  const minutes = Math.max(1, Math.round(ms / 60_000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours}u ${rest}m` : `${hours}u`;
}

function clock(value: unknown) {
  const ms = timestampMs(value);
  if (!ms) return "—";
  const now = new Date();
  const date = new Date(ms);
  const sameDay = now.toDateString() === date.toDateString();
  const time = new Intl.DateTimeFormat("nl-NL", { hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
  if (sameDay) return `Vandaag ${time}`;
  return new Intl.DateTimeFormat("nl-NL", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}

function exactClock(value: unknown) {
  const ms = timestampMs(value);
  if (!ms) return "—";
  return new Intl.DateTimeFormat("nl-NL", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(ms));
}

function pairLabel(symbol: string) {
  const value = String(symbol || "").toUpperCase();
  if (!value) return "";
  if (value.endsWith("USDT")) return `${value.slice(0, -4)}/USDT`;
  if (value.endsWith("USDC")) return `${value.slice(0, -4)}/USDC`;
  return value;
}

function averageEntry(item: NewsItem, events: TradeEvent[]) {
  return weightedAverageEntry(events) ?? item.averageEntry ?? item.entryPrice ?? null;
}

function dcaCount(item: NewsItem, events: TradeEvent[]) {
  const real = events.filter((event) => String(event.kind || "").toLowerCase() === "dca").length;
  return real || number(item.dcaCount) || 0;
}

function distanceToBreakEven(item: NewsItem) {
  const current = number(item.currentPrice);
  const be = number(item.breakEvenPrice) ?? number(item.averageEntry) ?? number(item.entryPrice);
  if (current === null || current <= 0 || be === null || be <= 0) return null;
  const short = item.side.toUpperCase() === "SHORT";
  return short ? ((current - be) / current) * 100 : ((be - current) / current) * 100;
}

function activePositionStub(position: Record<string, unknown>): NewsItem {
  const symbol = String(position.symbol || "").toUpperCase();
  const side = String(position.side || position.positionSide || "").toUpperCase();
  const ladder = position.strategy2DcaLadder as Record<string, unknown> | undefined;
  const tp = position.strategy2Tp as Record<string, unknown> | undefined;
  return {
    id: `position:${symbol}:${side}`,
    type: "position",
    tone: "recovery",
    filter: "updates",
    priority: 0,
    occurredAt: Date.now(),
    eyebrow: "UPDATE",
    symbol,
    side,
    title: `${baseAsset(symbol)} positie`,
    pnlUsd: number(position.unrealizedPnl) ?? number(position.unRealizedProfit),
    roiPct: null,
    leverage: number(position.leverage),
    dcaCount: number(position.dcaCount) ?? number(ladder?.filledDcaCount),
    entryPrice: number(position.entryPrice),
    averageEntry: number(position.averageEntry) ?? number(position.entryPrice),
    currentPrice: number(position.markPrice),
    exitPrice: null,
    breakEvenPrice: number(tp?.breakEvenPrice) ?? number(position.averageEntry) ?? number(position.entryPrice),
    liquidationDistancePct: null,
    feesUsd: null,
    durationMs: null,
    openedAt: position.openedAt ?? null,
    closedAt: null,
    notionalUsd: number(position.notionalUsd),
    position,
    source: position,
  };
}

function Icon({ name }: { name: "news" | "trophy" | "alert" | "recovery" | "portfolio" | "chart" | "clock" | "close" | "arrow" }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.9, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  if (name === "trophy") return <svg viewBox="0 0 24 24" aria-hidden="true"><path {...common} d="M8 4h8v5a4 4 0 0 1-8 0V4Z"/><path {...common} d="M8 6H5v1a4 4 0 0 0 4 4M16 6h3v1a4 4 0 0 1-4 4M12 13v4M9 20h6M10 17h4"/></svg>;
  if (name === "alert") return <svg viewBox="0 0 24 24" aria-hidden="true"><path {...common} d="m12 3 9 16H3L12 3Z"/><path {...common} d="M12 9v4M12 17h.01"/></svg>;
  if (name === "recovery") return <svg viewBox="0 0 24 24" aria-hidden="true"><path {...common} d="M4 17V7M4 17h16"/><path {...common} d="m7 14 4-4 3 3 5-7"/></svg>;
  if (name === "portfolio") return <svg viewBox="0 0 24 24" aria-hidden="true"><path {...common} d="M12 3v9h9"/><path {...common} d="M20.5 14.5A9 9 0 1 1 9.5 3.5"/></svg>;
  if (name === "chart") return <svg viewBox="0 0 24 24" aria-hidden="true"><path {...common} d="M4 20V10M10 20V4M16 20v-7M22 20V7"/></svg>;
  if (name === "clock") return <svg viewBox="0 0 24 24" aria-hidden="true"><circle {...common} cx="12" cy="12" r="9"/><path {...common} d="M12 7v5l3 2"/></svg>;
  if (name === "close") return <svg viewBox="0 0 24 24" aria-hidden="true"><path {...common} d="m6 6 12 12M18 6 6 18"/></svg>;
  if (name === "arrow") return <svg viewBox="0 0 24 24" aria-hidden="true"><path {...common} d="M5 12h14M14 7l5 5-5 5"/></svg>;
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path {...common} d="M5 4h14v16H5z"/><path {...common} d="M8 8h8M8 12h5M8 16h8"/></svg>;
}

function chartConfig(item: NewsItem, timeframe: NewsTimeframe) {
  const opened = timestampMs(item.openedAt);
  const ended = timestampMs(item.closedAt) || Date.now();
  const span = opened && ended > opened ? ended - opened : 0;
  if (item.closedAt && span > 0) {
    if (span <= 2 * 60 * 60 * 1000) return { interval: "1m", limit: 180 };
    if (span <= 12 * 60 * 60 * 1000) return { interval: "5m", limit: 180 };
    if (span <= 48 * 60 * 60 * 1000) return { interval: "15m", limit: 200 };
    return { interval: "1h", limit: 240 };
  }
  return candleConfigForTimeframe(timeframe) as { interval: string; limit: number };
}

async function fetchCandles(item: NewsItem, timeframe: NewsTimeframe) {
  if (!item.symbol) return [] as Candle[];
  const cfg = chartConfig(item, timeframe);
  const before = timestampMs(item.closedAt) || Date.now();
  const params = new URLSearchParams({
    exchange: "aster",
    symbol: item.symbol,
    interval: cfg.interval,
    limit: String(cfg.limit),
    before: String(before),
  });
  const response = await fetch(`/api/market-data?${params}`, { cache: "no-store" });
  if (!response.ok) throw new Error("Koersgrafiek is tijdelijk niet beschikbaar.");
  const payload = await response.json() as { candles?: Candle[] };
  return Array.isArray(payload.candles) ? payload.candles.filter((row) =>
    Number.isFinite(Number(row.time)) &&
    Number.isFinite(Number(row.open)) &&
    Number.isFinite(Number(row.high)) &&
    Number.isFinite(Number(row.low)) &&
    Number.isFinite(Number(row.close))
  ) : [];
}

function visibleCandles(item: NewsItem, candles: Candle[]) {
  if (!candles.length) return [];
  const opened = timestampMs(item.openedAt);
  const closed = timestampMs(item.closedAt);
  if (!opened) return candles.slice(-100);
  const bounded = candles.filter((candle) => {
    const at = Number(candle.time) * 1000;
    return at >= opened - 60_000 && (!closed || at <= closed + 60_000);
  });
  return (bounded.length >= 6 ? bounded : candles).slice(-120);
}

function TradeMiniChart({ item, candles, events, large = false }: { item: NewsItem; candles: Candle[]; events: TradeEvent[]; large?: boolean }) {
  const rows = visibleCandles(item, candles);
  if (!rows.length) {
    return <div className={`${styles.chartShell} ${large ? styles.chartLarge : ""}`}>
      <div className={styles.chartHead}><strong>{pairLabel(item.symbol)}</strong>{item.leverage ? <span>{Math.round(item.leverage)}x</span> : null}</div>
      <div className={styles.chartEmpty}>Koersdata laden…</div>
    </div>;
  }

  const W = 440;
  const H = large ? 300 : 238;
  const pad = { l: 18, r: 54, t: 28, b: 28 };
  const min = Math.min(...rows.map((row) => row.low));
  const max = Math.max(...rows.map((row) => row.high));
  const spread = Math.max(max - min, Math.max(max, 1) * 0.001);
  const priceMin = min - spread * 0.08;
  const priceMax = max + spread * 0.12;
  const firstTime = rows[0].time * 1000;
  const lastTime = rows[rows.length - 1].time * 1000;
  const timeSpan = Math.max(1, lastTime - firstTime);
  const x = (time: number) => pad.l + ((time - firstTime) / timeSpan) * (W - pad.l - pad.r);
  const y = (value: number) => pad.t + ((priceMax - value) / (priceMax - priceMin)) * (H - pad.t - pad.b);
  const candleWidth = Math.max(1.5, Math.min(5, (W - pad.l - pad.r) / rows.length * 0.55));
  const chartEvents = events.filter((event) => {
    const at = timestampMs(event.timestampMs || event.at);
    const p = number(event.price);
    return at >= firstTime - 120_000 && at <= lastTime + 120_000 && p !== null;
  }).slice(-12);

  const priceTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => priceMax - (priceMax - priceMin) * ratio);
  const timeTicks = [0, 0.33, 0.66, 1].map((ratio) => firstTime + timeSpan * ratio);

  return <div className={`${styles.chartShell} ${large ? styles.chartLarge : ""}`}>
    <div className={styles.chartHead}>
      <strong>{pairLabel(item.symbol)}</strong>
      <span className={styles.chartSide}>{item.side}</span>
      {item.leverage ? <span>{Math.round(item.leverage)}x</span> : null}
    </div>
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Werkelijke koersgrafiek en fills voor ${pairLabel(item.symbol)}`}>
      {priceTicks.map((tick, index) => <g key={`p-${index}`}>
        <line className={styles.gridLine} x1={pad.l} x2={W-pad.r} y1={y(tick)} y2={y(tick)}/>
        <text className={styles.axisText} x={W-pad.r+8} y={y(tick)+4}>{tick < 1 ? tick.toFixed(4) : tick.toFixed(2)}</text>
      </g>)}
      {timeTicks.map((tick, index) => <g key={`t-${index}`}>
        <line className={styles.gridLine} x1={x(tick)} x2={x(tick)} y1={pad.t} y2={H-pad.b}/>
        <text className={styles.axisText} x={x(tick)} y={H-7} textAnchor={index === 0 ? "start" : index === 3 ? "end" : "middle"}>
          {new Intl.DateTimeFormat("nl-NL", { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(tick))}
        </text>
      </g>)}
      {rows.map((row, index) => {
        const cx = x(row.time * 1000);
        const up = row.close >= row.open;
        const openY = y(row.open);
        const closeY = y(row.close);
        const top = Math.min(openY, closeY);
        const height = Math.max(1.6, Math.abs(closeY - openY));
        return <g key={`${row.time}-${index}`} className={up ? styles.candleUp : styles.candleDown}>
          <line x1={cx} x2={cx} y1={y(row.high)} y2={y(row.low)}/>
          <rect x={cx-candleWidth/2} y={top} width={candleWidth} height={height} rx=".8"/>
        </g>;
      })}
      {chartEvents.map((event, index) => {
        const at = timestampMs(event.timestampMs || event.at);
        const p = number(event.price);
        if (p === null) return null;
        const kind = String(event.kind || "").toLowerCase();
        const label = kind === "entry" ? "Entry" : kind === "close" ? "Exit" : `DCA${event.dcaNumber ? ` ${event.dcaNumber}` : ""}`;
        return <g key={event.id || `${kind}-${index}`} className={`${styles.eventMark} ${kind === "entry" ? styles.eventEntry : kind === "close" ? styles.eventClose : styles.eventDca}`}>
          <circle cx={x(at)} cy={y(p)} r={large ? 6.3 : 5.3}/>
          <circle cx={x(at)} cy={y(p)} r={large ? 10 : 8.5}/>
          <text x={x(at)} y={Math.max(18, y(p)-13)} textAnchor="middle">{label}</text>
        </g>;
      })}
    </svg>
  </div>;
}

function metric(label: string, value: string, tone?: "profit" | "loss") {
  return <div className={styles.metric}><span>{label}</span><strong data-tone={tone || ""}>{value}</strong></div>;
}

function winnerStory(item: NewsItem, events: TradeEvent[]) {
  const entry = averageEntry(item, events);
  const count = dcaCount(item, events);
  const opened = timestampMs(item.openedAt);
  const closed = timestampMs(item.closedAt);
  const startText = opened ? `opende om ${new Intl.DateTimeFormat("nl-NL", { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(opened))}` : "opende een positie";
  const dcaText = count ? ` Tijdens de cyclus werden ${count} echte DCA-order${count === 1 ? "" : "s"} uitgevoerd.` : " Er waren geen bevestigde DCA-fills in deze cyclus.";
  const entryText = entry ? ` De gemiddelde instap kwam op ${price(entry)}.` : "";
  const closeText = closed ? ` Om ${new Intl.DateTimeFormat("nl-NL", { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(closed))} werd de positie gesloten` : " De positie werd gesloten";
  return `${baseAsset(item.symbol)} ${startText}.${dcaText}${entryText}${closeText} met ${money(item.pnlUsd, true)} netto gerealiseerde PnL volgens Aster.`;
}

function pressureStory(item: NewsItem, candles: Candle[]) {
  const rows = visibleCandles(item, candles);
  let movement = "";
  if (rows.length > 1 && item.currentPrice) {
    const first = rows[0].close;
    const current = number(item.currentPrice);
    if (current !== null && first > 0) {
      const raw = ((current - first) / first) * 100;
      const directional = item.side === "SHORT" ? -raw : raw;
      movement = ` De koersbeweging over het zichtbare venster is ${percent(directional, true)} voor deze ${item.side.toLowerCase()}-positie.`;
    }
  }
  const dc = number(item.dcaCount);
  const be = distanceToBreakEven(item);
  return `${baseAsset(item.symbol)} staat momenteel ${money(item.pnlUsd, true)} open PnL.${movement}${dc ? ` Er zijn ${Math.round(dc)} DCA-fills geregistreerd.` : ""}${be !== null ? ` Break-even ligt circa ${Math.abs(be).toFixed(2).replace(".", ",")}% van de huidige prijs.` : ""}`;
}

function recoveryStory(item: NewsItem) {
  const recovery = number(item.roiPct);
  const adverse = number(item.source?.adversePrice);
  const be = distanceToBreakEven(item);
  return `${baseAsset(item.symbol)} is ${recovery === null ? "" : `${recovery.toFixed(2).replace(".", ",")}% `}hersteld vanaf het werkelijke ${item.side === "SHORT" ? "hoogste" : "laagste"} candlepunt${adverse ? ` (${price(adverse)})` : ""} binnen het gekozen tijdvenster. De positie staat nog ${money(item.pnlUsd, true)} open PnL${be !== null ? ` en circa ${Math.abs(be).toFixed(2).replace(".", ",")}% van break-even` : ""}.`;
}

function dcaStory(item: NewsItem) {
  const latest = item.source?.latestDca as Record<string, unknown> | undefined;
  return `${baseAsset(item.symbol)} heeft een bevestigde DCA-fill uitgevoerd${latest?.price ? ` op ${price(latest.price)}` : ""}. Alleen werkelijk uitgevoerde fills worden in deze feed als DCA gemarkeerd.`;
}

function storyFor(item: NewsItem, events: TradeEvent[], candles: Candle[]) {
  if (item.type === "winner") return winnerStory(item, events);
  if (item.type === "pressure") return pressureStory(item, candles);
  if (item.type === "recovery") return recoveryStory(item);
  if (item.type === "update") return dcaStory(item);
  const source = item.source || {};
  return `In ${timeframeLabel(String(source.timeframe || "24h"))} zijn ${source.profitableCount || 0} winstgevende trades gesloten. De gerealiseerde winst uit die winnaars is ${money(item.pnlUsd, true)}; totale gerealiseerde PnL over alle gesloten trades in dit venster is ${money(source.totalPnlUsd, true)}.`;
}

function cardMetrics(item: NewsItem, events: TradeEvent[]) {
  if (item.type === "winner") return [
    ["ROI", percent(item.roiPct, true), item.roiPct && item.roiPct > 0 ? "profit" : undefined],
    ["Duur", duration(item.durationMs), undefined],
    ["DCA's", String(dcaCount(item, events)), undefined],
    ["Entry", price(averageEntry(item, events)), undefined],
    ["Exit", price(item.exitPrice), undefined],
  ] as Array<[string,string, "profit" | "loss" | undefined]>;
  if (item.type === "pressure") return [
    ["Koers vs entry", percent(item.roiPct, true), "loss"],
    ["Huidig verlies", money(item.pnlUsd, true), "loss"],
    ["DCA's", String(item.dcaCount ?? dcaCount(item, events)), undefined],
    ["Gem. entry", price(averageEntry(item, events)), undefined],
    ["Liq. afstand", item.liquidationDistancePct === null || item.liquidationDistancePct === undefined ? "—" : percent(item.liquidationDistancePct), undefined],
  ] as Array<[string,string, "profit" | "loss" | undefined]>;
  if (item.type === "recovery") return [
    ["Huidig verlies", money(item.pnlUsd, true), "loss"],
    ["Afstand BE", (() => { const value = distanceToBreakEven(item); return value === null ? "—" : percent(Math.abs(value)); })(), undefined],
    ["DCA's", String(item.dcaCount ?? dcaCount(item, events)), undefined],
    ["Laagste prijs", price(item.source?.adversePrice), undefined],
  ] as Array<[string,string, "profit" | "loss" | undefined]>;
  if (item.type === "update") return [
    ["DCA's", String(item.source?.dcaCount || item.dcaCount || 0), undefined],
    ["Gem. entry", price(averageEntry(item, events)), undefined],
    ["Huidige prijs", price(item.currentPrice), undefined],
    ["Open PnL", money(item.pnlUsd, true), item.pnlUsd && item.pnlUsd < 0 ? "loss" : item.pnlUsd && item.pnlUsd > 0 ? "profit" : undefined],
  ] as Array<[string,string, "profit" | "loss" | undefined]>;
  return [];
}

function portfolioMetrics(item: NewsItem) {
  const source = item.source || {};
  return [
    ["Trades gesloten", String(source.closedCount || 0), "trophy"],
    ["Gerealiseerde winst", money(item.pnlUsd, true), "chart"],
    ["Winratio", source.winRate === null || source.winRate === undefined ? "—" : percent(source.winRate), "recovery"],
    ["Tijdsperiode", timeframeLabel(String(source.timeframe || "24h")), "clock"],
  ] as const;
}

function NewsCard({ item, events, candles, onOpen }: { item: NewsItem; events: TradeEvent[]; candles: Candle[]; onOpen: (item: NewsItem) => void }) {
  const icon = item.tone === "profit" ? "trophy" : item.tone === "loss" ? "alert" : item.tone === "portfolio" ? "portfolio" : "recovery";
  if (item.type === "portfolio") {
    return <article className={`${styles.portfolioCard} ${styles.card}`} data-tone="portfolio">
      <div className={styles.portfolioCopy}>
        <div className={styles.eyebrow}><span className={styles.eyebrowIcon}><Icon name={icon}/></span>{item.eyebrow}<time>{clock(item.occurredAt)}</time></div>
        <div className={styles.portfolioTitleRow}><h2>{item.title}</h2><strong>{money(item.pnlUsd, true)}</strong></div>
        <p>{storyFor(item, events, candles)}</p>
      </div>
      <div className={styles.portfolioStats}>
        {portfolioMetrics(item).map(([label, value, metricIcon]) => <div className={styles.portfolioMetric} key={label}>
          <span className={styles.portfolioMetricIcon}><Icon name={metricIcon}/></span>
          <strong>{value}</strong><small>{label}</small>
        </div>)}
      </div>
    </article>;
  }

  const mainValue = item.type === "recovery" ? percent(item.roiPct, true) : money(item.pnlUsd, true);
  return <article className={styles.card} data-tone={item.tone}>
    <section className={styles.cardCopy}>
      <div className={styles.eyebrow}>
        <span className={styles.eyebrowIcon}><Icon name={icon}/></span>
        {item.eyebrow}
        <time>{clock(item.occurredAt)}</time>
      </div>
      <h2>{item.title}</h2>
      <div className={styles.heroValue}>{mainValue}</div>
      <div className={styles.metrics}>
        {cardMetrics(item, events).map(([label, value, tone]) => <div key={label}>{metric(label, value, tone)}</div>)}
      </div>
      <p className={styles.story}>{storyFor(item, events, candles)}</p>
      <button className={styles.cta} type="button" onClick={() => onOpen(item)}>
        {item.closedAt ? "Bekijk details" : "Bekijk positie"} <span><Icon name="arrow"/></span>
      </button>
    </section>
    <section className={styles.cardChart}>
      <TradeMiniChart item={item} candles={candles} events={events}/>
    </section>
  </article>;
}

function DetailView({ detail, onClose }: { detail: DetailState; onClose: () => void }) {
  const { item, events, candles, loading, error } = detail;
  const entry = averageEntry(item, events);
  const dc = dcaCount(item, events);
  return <div className={styles.detailBackdrop} role="dialog" aria-modal="true" aria-label={`Trade details ${pairLabel(item.symbol)}`} onMouseDown={(event) => {
    if (event.currentTarget === event.target) onClose();
  }}>
    <div className={styles.detailPanel}>
      <header className={styles.detailHeader}>
        <div>
          <span>{item.closedAt ? "VOLLEDIGE TRADE STORY" : "ACTIEVE POSITIE"}</span>
          <h2>{pairLabel(item.symbol)} <small>{item.side}{item.leverage ? ` · ${Math.round(item.leverage)}x` : ""}</small></h2>
        </div>
        <button type="button" onClick={onClose} aria-label="Sluiten"><Icon name="close"/></button>
      </header>

      <div className={styles.detailScroll}>
        {loading && <div className={styles.detailNotice}>Bevestigde fills en koersdata laden…</div>}
        {error && <div className={styles.detailError}>{error}</div>}
        <div className={styles.detailSummary}>
          {metric("Netto PnL", money(item.pnlUsd, true), item.pnlUsd && item.pnlUsd < 0 ? "loss" : "profit")}
          {metric("ROI", percent(item.roiPct, true), item.roiPct && item.roiPct < 0 ? "loss" : item.roiPct && item.roiPct > 0 ? "profit" : undefined)}
          {metric("DCA's", String(dc))}
          {metric("Gem. entry", price(entry))}
          {item.closedAt ? metric("Exit", price(item.exitPrice)) : metric("Mark", price(item.currentPrice))}
          {metric("Fees", money(item.feesUsd))}
        </div>

        <TradeMiniChart item={item} candles={candles} events={events} large/>

        <section className={styles.detailStory}>
          <h3>Het verhaal van deze trade</h3>
          <p>{storyFor(item, events, candles)}</p>
        </section>

        <section className={styles.timeline}>
          <h3>Execution timeline</h3>
          {events.length ? events.map((event, index) => {
            const kind = String(event.kind || "").toLowerCase();
            const label = kind === "entry" ? "Initial entry" : kind === "close" ? "Exit" : `DCA ${event.dcaNumber || index}`;
            return <div className={styles.timelineRow} key={event.id || `${event.timestampMs}-${index}`}>
              <span data-kind={kind}/>
              <div><strong>{label}</strong><small>{exactClock(event.timestampMs || event.at)}</small></div>
              <div><strong>{price(event.price)}</strong><small>{event.quantity ? `${event.quantity} qty` : ""}</small></div>
            </div>;
          }) : <p className={styles.timelineEmpty}>Voor deze cyclus zijn nog geen bevestigde fill-events beschikbaar.</p>}
        </section>

        <section className={styles.detailFacts}>
          <h3>Trade summary</h3>
          <dl>
            <div><dt>Pair</dt><dd>{pairLabel(item.symbol)}</dd></div>
            <div><dt>Richting</dt><dd>{item.side || "—"}</dd></div>
            <div><dt>Leverage</dt><dd>{item.leverage ? `${Math.round(item.leverage)}x` : "—"}</dd></div>
            <div><dt>Start</dt><dd>{exactClock(item.openedAt || events[0]?.timestampMs)}</dd></div>
            <div><dt>Einde</dt><dd>{item.closedAt ? exactClock(item.closedAt) : "Actief"}</dd></div>
            <div><dt>Duur</dt><dd>{duration(item.durationMs || (timestampMs(item.closedAt) && timestampMs(item.openedAt) ? timestampMs(item.closedAt)-timestampMs(item.openedAt) : null))}</dd></div>
            <div><dt>Netto PnL</dt><dd>{money(item.pnlUsd, true)}</dd></div>
            <div><dt>Fees</dt><dd>{money(item.feesUsd)}</dd></div>
          </dl>
        </section>
      </div>
    </div>
  </div>;
}

export function NewsView() {
  const [account, setAccount] = useState<Record<string, unknown>>(EMPTY);
  const [history, setHistory] = useState<Record<string, unknown>>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<NewsFilter>("all");
  const [timeframe, setTimeframe] = useState<NewsTimeframe>("24h");
  const [candlesById, setCandlesById] = useState<Record<string, Candle[]>>({});
  const [detail, setDetail] = useState<DetailState | null>(null);
  const requestGeneration = useRef(0);

  const refresh = useCallback(async () => {
    const generation = ++requestGeneration.current;
    try {
      const [nextAccount, nextHistory] = await Promise.all([
        authenticatedRequest("/api/exchanges/aster", { cache: "no-store" }),
        authenticatedRequest("/api/exchanges/aster/closed-trades", { cache: "no-store" }),
      ]);
      if (generation !== requestGeneration.current) return;
      setAccount(nextAccount && typeof nextAccount === "object" ? nextAccount as Record<string, unknown> : EMPTY);
      setHistory(nextHistory && typeof nextHistory === "object" ? nextHistory as Record<string, unknown> : EMPTY);
      setError("");
    } catch (reason) {
      if (generation !== requestGeneration.current) return;
      setError(reason instanceof Error ? reason.message : "Persoonlijk tradenieuws kon niet worden geladen.");
    } finally {
      if (generation === requestGeneration.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 60_000);
    const visible = () => { if (document.visibilityState === "visible") void refresh(); };
    document.addEventListener("visibilitychange", visible);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [refresh]);

  const baseItems = useMemo(() => buildTradeNews({ account, history, timeframe, now: Date.now() }) as NewsItem[], [account, history, timeframe]);
  const positions = useMemo(() => accountPositions(account) as Record<string, unknown>[], [account]);
  const positionStubs = useMemo(() => positions.map(activePositionStub), [positions]);

  const chartTargets = useMemo(() => {
    const byId = new Map<string, NewsItem>();
    for (const item of [...baseItems.filter((item) => item.type !== "portfolio"), ...positionStubs]) {
      if (item.symbol && !byId.has(item.id)) byId.set(item.id, item);
      if (byId.size >= 16) break;
    }
    return Array.from(byId.values());
  }, [baseItems, positionStubs]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const results = await Promise.allSettled(chartTargets.map(async (item) => ({ id: item.id, candles: await fetchCandles(item, timeframe) })));
      if (cancelled) return;
      setCandlesById((current) => {
        const next = { ...current };
        for (const result of results) {
          if (result.status === "fulfilled") next[result.value.id] = result.value.candles;
        }
        return next;
      });
    };
    if (chartTargets.length) void load();
    return () => { cancelled = true; };
  }, [chartTargets, timeframe]);

  const items = useMemo(() => {
    const next: NewsItem[] = [...baseItems];
    for (const stub of positionStubs) {
      const candles = candlesById[stub.id] || [];
      const recovery = recoveryFromCandles(stub.position, candles, timeframe, Date.now()) as NewsItem | null;
      if (recovery) next.push(recovery);
      const events = activityEventsForItem(stub, history) as TradeEvent[];
      const dca = dcaUpdateFromEvents(stub, events, timeframe, Date.now()) as NewsItem | null;
      if (dca) next.push(dca);
    }
    const unique = new Map<string, NewsItem>();
    for (const item of next) {
      const current = unique.get(item.id);
      if (!current || item.priority > current.priority || item.occurredAt > current.occurredAt) unique.set(item.id, item);
    }
    return Array.from(unique.values()).sort((a, b) => (b.priority - a.priority) || (b.occurredAt - a.occurredAt));
  }, [baseItems, positionStubs, candlesById, history, timeframe]);

  const filtered = useMemo(() => filterTradeNews(items, filter) as NewsItem[], [items, filter]);

  const eventsFor = useCallback((item: NewsItem) => activityEventsForItem(item, history) as TradeEvent[], [history]);
  const candlesFor = useCallback((item: NewsItem) => {
    if (candlesById[item.id]) return candlesById[item.id];
    const samePosition = positionStubs.find((stub) => stub.symbol === item.symbol && stub.side === item.side);
    return samePosition ? candlesById[samePosition.id] || [] : [];
  }, [candlesById, positionStubs]);

  const openDetail = useCallback(async (item: NewsItem) => {
    const fallbackEvents = eventsFor(item);
    const fallbackCandles = candlesFor(item);
    setDetail({ item, events: fallbackEvents, candles: fallbackCandles, loading: true, error: "" });
    try {
      const query = new URLSearchParams({ symbol: item.symbol, side: item.side.toLowerCase() });
      const closedAt = timestampMs(item.closedAt);
      if (closedAt) query.set("closed_at_ms", String(closedAt));
      const [eventResult, candleResult] = await Promise.allSettled([
        authenticatedRequest(`/api/exchanges/aster/trade-events?${query}`, { cache: "no-store" }),
        fetchCandles(item, "cycle"),
      ]);
      const exactEvents = eventResult.status === "fulfilled" && Array.isArray((eventResult.value as Record<string, unknown>)?.events)
        ? ((eventResult.value as Record<string, unknown>).events as TradeEvent[])
        : fallbackEvents;
      const exactCandles = candleResult.status === "fulfilled" ? candleResult.value : fallbackCandles;
      const detailError = eventResult.status === "rejected" && candleResult.status === "rejected"
        ? "Een deel van de detaildata kon niet opnieuw worden bevestigd; de laatst bevestigde data wordt getoond."
        : "";
      setDetail((current) => current?.item.id === item.id ? { item, events: exactEvents, candles: exactCandles, loading: false, error: detailError } : current);
    } catch (reason) {
      setDetail((current) => current?.item.id === item.id ? {
        ...current,
        loading: false,
        error: reason instanceof Error ? reason.message : "Details konden niet opnieuw worden bevestigd.",
      } : current);
    }
  }, [eventsFor, candlesFor]);

  const equity = number(account.equity);
  const openPnl = number(account.unrealizedPnl);
  const activePositions = number(account.activePositions) ?? positions.length;

  return <main className={styles.news}>
    <section className={styles.pageHead}>
      <div className={styles.heading}>
        <span className={styles.headingIcon}><Icon name="news"/></span>
        <div><h1>Mijn Nieuws</h1><p>Jouw trades. Jouw verhaal. Automatisch gegenereerd.</p></div>
      </div>
      <div className={styles.timeSelectWrap}>
        <label htmlFor="trade-news-timeframe">Tijdsvenster</label>
        <select id="trade-news-timeframe" value={timeframe} onChange={(event) => setTimeframe(event.target.value as NewsTimeframe)}>
          {TRADE_NEWS_TIMEFRAMES.map((item: { key: NewsTimeframe; label: string }) => <option value={item.key} key={item.key}>{item.label}</option>)}
        </select>
      </div>
    </section>

    <section className={styles.accountStrip} aria-label="Actueel portfolio">
      <div><span>Portfolio</span><strong>{money(equity)}</strong></div>
      <div><span>Open PnL</span><strong data-tone={openPnl !== null && openPnl < 0 ? "loss" : "profit"}>{money(openPnl, true)}</strong></div>
      <div><span>Actieve posities</span><strong>{activePositions ?? "—"}</strong></div>
      <div className={styles.liveState}><i/>LIVE · echte Aster-data</div>
    </section>

    <nav className={styles.filters} aria-label="Nieuwsfilters">
      {TRADE_NEWS_FILTERS.map((item: { key: NewsFilter; label: string }) => <button
        type="button"
        key={item.key}
        aria-pressed={filter === item.key}
        className={filter === item.key ? styles.filterActive : ""}
        onClick={() => setFilter(item.key)}
      >
        <span className={styles.filterIcon}><Icon name={item.key === "wins" ? "trophy" : item.key === "pressure" ? "alert" : item.key === "portfolio" ? "portfolio" : item.key === "updates" ? "recovery" : "news"}/></span>
        {item.label}
      </button>)}
    </nav>

    {error && <section className={styles.errorBanner}><strong>Live data tijdelijk beperkt.</strong><span>{error}</span><button type="button" onClick={() => void refresh()}>Opnieuw</button></section>}
    {loading && !items.length && <section className={styles.loading}><span/><strong>Jouw trade stories worden opgebouwd uit bevestigde fills…</strong></section>}

    {!loading && !filtered.length && <section className={styles.empty}>
      <span><Icon name="news"/></span>
      <strong>Geen materiële update in dit tijdsvenster</strong>
      <p>Stabiele trades blijven bewust stil. Zodra een trade sluit, onder druk komt, herstelt of een echte DCA uitvoert, verschijnt hier een persoonlijk nieuwsitem.</p>
    </section>}

    <section className={styles.feed}>
      {filtered.map((item) => {
        const events = eventsFor(item);
        return <NewsCard key={item.id} item={item} events={events} candles={candlesFor(item)} onOpen={(value) => void openDetail(value)}/>;
      })}
    </section>

    <footer className={styles.feedFooter}>
      <span><i/></span>
      <p>Geen extern cryptonieuws. Alleen gebeurtenissen uit jouw eigen portfolio, Aster-fills en werkelijke koersdata.</p>
    </footer>

    {detail && <DetailView detail={detail} onClose={() => setDetail(null)}/>} 
  </main>;
}
