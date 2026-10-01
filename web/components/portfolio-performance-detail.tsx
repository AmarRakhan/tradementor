"use client";

import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { cashflowAdjustedPortfolioSeries } from "@/lib/portfolio-koers-chart.mjs";

export type PerformanceInitialTab = "per-day" | "analysis" | "average" | "explanation";

type HistoryRow = {
  date: string;
  startEquity: number;
  endEquity: number;
  usdChange: number;
  percentage: number;
  externalCashflowUsd?: number;
  source?: string;
};

type CashflowBreakdown = {
  count?: number;
  depositsUsd?: number;
  withdrawalsUsd?: number;
  adjustmentsUsd?: number;
  netExternalCashflowUsd?: number;
  ledgerTypes?: string[];
};

type LedgerBreakdown = {
  realizedPnlUsd?: number;
  fundingUsd?: number;
  feesUsd?: number;
  liquidationUsd?: number;
  otherTradingAdjustmentsUsd?: number;
  knownPerformanceLedgerUsd?: number;
  equityResidualUsd?: number;
  equityResidualReliableAsUnrealizedPnl?: boolean;
  equityResidualLabel?: string;
  realizedEventCount?: number;
  positiveRealizedEventCount?: number;
  negativeRealizedEventCount?: number;
  ledgerTypes?: string[];
};

type DailyGrowth = {
  reliable?: boolean;
  todayPercentage?: number;
  todayUsd?: number;
  averageDailyPercentage?: number;
  measuredDays?: number;
  measurementStartDate?: string;
  referenceDate?: string;
  dayStartTimestampMs?: number;
  dayStartEquity?: number;
  currentEquity?: number;
  cashflowAdjustedEndingEquity?: number;
  dayExternalCashflowUsd?: number;
  cashflowBreakdown?: CashflowBreakdown;
  performanceLedgerBreakdown?: LedgerBreakdown;
  performanceMethod?: string;
  cashflowLedgerComplete?: boolean;
  history?: HistoryRow[];
  blockReason?: string;
};

type DayDetail = {
  reliable?: boolean;
  date?: string;
  startEquity?: number;
  endEquity?: number;
  usdChange?: number;
  percentage?: number;
  externalCashflowUsd?: number;
  cashflowBreakdown?: CashflowBreakdown;
  performanceLedgerBreakdown?: LedgerBreakdown;
  performanceMethod?: string;
  source?: string;
  blockReason?: string;
};

type ChartCandle = { time: number; atMs?: number; close: number };
type ChartMarker = { time?: number; kind?: string; amountUsd?: number };
type ChartPayload = { candles?: ChartCandle[]; markers?: ChartMarker[] };

const TABS: Array<{ id: PerformanceInitialTab; label: string }> = [
  { id: "per-day", label: "Per dag" },
  { id: "analysis", label: "Analyse" },
  { id: "average", label: "Gemiddeld" },
  { id: "explanation", label: "Uitleg" },
];

const finite = (value: unknown): number | null => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const signedMoney = (value: unknown) => {
  const number = finite(value);
  if (number === null) return "—";
  const sign = number > 0 ? "+" : number < 0 ? "−" : "";
  return `${sign}US$ ${Math.abs(number).toLocaleString("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

const money = (value: unknown) => {
  const number = finite(value);
  return number === null ? "—" : `US$ ${number.toLocaleString("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

const percent = (value: unknown) => {
  const number = finite(value);
  if (number === null) return "—";
  return `${number > 0 ? "+" : ""}${number.toLocaleString("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
};

const tone = (value: unknown) => {
  const number = finite(value);
  return number !== null && number > 0 ? "positive" : number !== null && number < 0 ? "negative" : "neutral";
};

const dateLabel = (value: string | undefined, withYear = true) => {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return "—";
  const date = new Date(`${value}T12:00:00`);
  return new Intl.DateTimeFormat("nl-NL", withYear
    ? { day: "numeric", month: "long", year: "numeric", timeZone: "Europe/Amsterdam" }
    : { day: "numeric", month: "short", timeZone: "Europe/Amsterdam" }).format(date);
};

const average = (rows: HistoryRow[]) => rows.length
  ? rows.reduce((sum, row) => sum + Number(row.percentage || 0), 0) / rows.length
  : null;

function todayRow(data: DailyGrowth | null): HistoryRow | null {
  if (!data?.reliable || !data.referenceDate) return null;
  const start = finite(data.dayStartEquity);
  const end = finite(data.currentEquity);
  const usd = finite(data.todayUsd);
  const pct = finite(data.todayPercentage);
  if ([start, end, usd, pct].some((value) => value === null)) return null;
  return {
    date: data.referenceDate,
    startEquity: start as number,
    endEquity: end as number,
    usdChange: usd as number,
    percentage: pct as number,
    externalCashflowUsd: finite(data.dayExternalCashflowUsd) ?? 0,
    source: "LIVE_DAILY_GROWTH",
  };
}

function Stat({ label, value, valueTone = "neutral", detail }: { label: string; value: string; valueTone?: "positive" | "negative" | "neutral"; detail?: string }) {
  return <span className="aps-performance-stat">
    <small>{label}</small>
    <strong className={`is-${valueTone}`}>{value}</strong>
    {detail ? <em>{detail}</em> : null}
  </span>;
}

function PerformanceSparkline({ daily, chart }: { daily: DailyGrowth; chart: ChartPayload | null }) {
  const points = useMemo(() => {
    const date = String(daily.referenceDate || "");
    const candles = (chart?.candles || []).filter((row) => {
      const stamp = Number(row.atMs || row.time * 1000);
      if (!stamp || !date) return false;
      const local = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Amsterdam", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(stamp));
      return local === date;
    });
    const adjusted = cashflowAdjustedPortfolioSeries(candles, chart?.markers || []) as Array<{ time: number; value: number }>;
    return adjusted.filter((row) => Number.isFinite(row.time) && Number.isFinite(row.value));
  }, [chart, daily.referenceDate]);

  if (points.length < 2) {
    return <div className="aps-performance-chart is-empty"><span>Intraday performance wordt opgebouwd uit de bestaande Portfolio Koers-metingen.</span></div>;
  }

  const width = 640, height = 190, padX = 16, padY = 16;
  const values = points.map((row) => row.value);
  const min = Math.min(...values), max = Math.max(...values);
  const range = Math.max(max - min, Math.abs(max) * 0.001, 0.01);
  const path = points.map((row, index) => {
    const x = padX + (index / Math.max(1, points.length - 1)) * (width - padX * 2);
    const y = padY + ((max - row.value) / range) * (height - padY * 2);
    return `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const end = points.at(-1)!;
  const endX = width - padX;
  const endY = padY + ((max - end.value) / range) * (height - padY * 2);
  const endTime = new Date(end.time * 1000).toLocaleTimeString("nl-NL", { timeZone: "Europe/Amsterdam", hour: "2-digit", minute: "2-digit" });

  return <div className="aps-performance-chart" aria-label="Cashflow-gecorrigeerde intraday performance">
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Performancegrafiek vandaag">
      <path className="aps-performance-gridline" d={`M16,${height / 2} H${width - 16}`} />
      <path className="aps-performance-line" d={path} />
      <circle className="aps-performance-dot" cx={endX} cy={endY} r="5" />
    </svg>
    <span className="aps-performance-axis start">00:00</span>
    <span className="aps-performance-axis end">{endTime}</span>
  </div>;
}

function LedgerBreakdownView({ detail, totalUsd, totalPct, compact = false }: { detail: DayDetail | DailyGrowth; totalUsd: unknown; totalPct: unknown; compact?: boolean }) {
  const ledger = detail.performanceLedgerBreakdown || {};
  const cashflow = detail.cashflowBreakdown || {};
  const rows = [
    ["Gesloten resultaat (realized PnL)", ledger.realizedPnlUsd],
    ["Open PnL / equity-rest", ledger.equityResidualUsd],
    ["Funding", ledger.fundingUsd],
    ["Handelskosten (fees)", ledger.feesUsd],
    ["Liquidatie / ADL", ledger.liquidationUsd],
    ["Overige trading adjustments", ledger.otherTradingAdjustmentsUsd],
  ] as Array<[string, unknown]>;

  return <section className={`aps-performance-card aps-performance-breakdown${compact ? " is-compact" : ""}`}>
    <header><div><small>OPBOUW</small><h3>Rendement {detail.date ? dateLabel(detail.date, false) : "vandaag"}</h3></div><span>audit</span></header>
    <div className="aps-performance-ledger">
      {rows.map(([label, value]) => <div key={label}><span>{label}</span><strong className={`is-${tone(value)}`}>{signedMoney(value)}</strong></div>)}
      <div className="is-cashflow"><span>Stortingen / opnames</span><strong>{signedMoney(cashflow.netExternalCashflowUsd ?? detail.externalCashflowUsd)}</strong><em>niet meegerekend als tradingrendement</em></div>
    </div>
    <div className="aps-performance-total">
      <span>Totaal rendement</span>
      <strong className={`is-${tone(totalUsd)}`}>{signedMoney(totalUsd)}</strong>
      <b className={`is-${tone(totalPct)}`}>{percent(totalPct)}</b>
    </div>
    {ledger.equityResidualReliableAsUnrealizedPnl === false ? <p className="aps-performance-note">De equity-rest sluit het dagtotaal auditbaar aan. Historisch is dit niet als zuivere unrealized PnL te bewijzen, omdat oude snapshots geen aparte open-PnL-component bewaren.</p> : null}
  </section>;
}

function DayDetails({ detail, loading }: { detail: DayDetail | null; loading: boolean }) {
  if (loading) return <div className="aps-performance-day-detail is-loading">Dagdetail laden…</div>;
  if (!detail) return null;
  if (!detail.reliable) return <div className="aps-performance-day-detail is-error"><b>{dateLabel(detail.date)}</b><span>{detail.blockReason || "Detail niet betrouwbaar beschikbaar."}</span></div>;
  const ledger = detail.performanceLedgerBreakdown || {};
  return <div className="aps-performance-day-detail">
    <header><div><small>DAGDETAIL</small><h4>{dateLabel(detail.date)}</h4></div><strong className={`is-${tone(detail.percentage)}`}>{percent(detail.percentage)}</strong></header>
    <div className="aps-performance-day-facts">
      <Stat label="Startwaarde" value={money(detail.startEquity)} />
      <Stat label="Eindwaarde" value={money(detail.endEquity)} />
      <Stat label="Verschil" value={signedMoney(detail.usdChange)} valueTone={tone(detail.usdChange)} />
      <Stat label="Rendement" value={percent(detail.percentage)} valueTone={tone(detail.percentage)} />
      <Stat label="PnL-ledgerevents" value={String(ledger.realizedEventCount ?? "—")} detail={ledger.realizedEventCount !== undefined ? `${ledger.positiveRealizedEventCount ?? 0} positief · ${ledger.negativeRealizedEventCount ?? 0} negatief` : undefined} />
      <Stat label="Externe cashflow" value={signedMoney(detail.cashflowBreakdown?.netExternalCashflowUsd ?? detail.externalCashflowUsd)} detail="uit rendement gefilterd" />
    </div>
    <LedgerBreakdownView detail={detail} totalUsd={detail.usdChange} totalPct={detail.percentage} compact />
  </div>;
}

function DailyTab({ daily, chart }: { daily: DailyGrowth; chart: ChartPayload | null }) {
  const [visibleCount, setVisibleCount] = useState(7);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [detail, setDetail] = useState<DayDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const rows = useMemo(() => {
    const map = new Map<string, HistoryRow>();
    for (const row of daily.history || []) if (row?.date) map.set(row.date, row);
    const live = todayRow(daily);
    if (live) map.set(live.date, live);
    return [...map.values()].sort((a, b) => b.date.localeCompare(a.date));
  }, [daily]);

  const selectDay = async (row: HistoryRow) => {
    if (selectedDate === row.date) {
      setSelectedDate(null);
      setDetail(null);
      return;
    }
    setSelectedDate(row.date);
    if (row.date === daily.referenceDate) {
      setDetail({
        reliable: daily.reliable,
        date: row.date,
        startEquity: daily.dayStartEquity,
        endEquity: daily.currentEquity,
        usdChange: daily.todayUsd,
        percentage: daily.todayPercentage,
        externalCashflowUsd: daily.dayExternalCashflowUsd,
        cashflowBreakdown: daily.cashflowBreakdown,
        performanceLedgerBreakdown: daily.performanceLedgerBreakdown,
        performanceMethod: daily.performanceMethod,
        source: "LIVE_DAILY_GROWTH",
      });
      return;
    }
    setDetailLoading(true);
    setDetail(null);
    try {
      const payload = await authenticatedRequest(`/api/exchanges/aster/portfolio-growth/daily-detail?date=${encodeURIComponent(row.date)}`, { cache: "no-store" }) as DayDetail;
      setDetail(payload);
    } catch (cause) {
      setDetail({ reliable: false, date: row.date, blockReason: cause instanceof Error ? cause.message : "Dagdetail kon niet worden geladen." });
    } finally {
      setDetailLoading(false);
    }
  };

  return <>
    <section className="aps-performance-card aps-performance-hero">
      <header><div><small>RENDEMENT VANDAAG</small><h3>{dateLabel(daily.referenceDate)}</h3></div><span>◫</span></header>
      <strong className={`aps-performance-big is-${tone(daily.todayPercentage)}`}>{percent(daily.todayPercentage)}</strong>
      <b className={`aps-performance-usd is-${tone(daily.todayUsd)}`}>{signedMoney(daily.todayUsd)}</b>
      <p>excl. stortingen &amp; opnames</p>
      <div className="aps-performance-hero-stats">
        <Stat label="Startwaarde" value={money(daily.dayStartEquity)} />
        <Stat label="Eindwaarde" value={money(daily.currentEquity)} />
        <Stat label="Verschil" value={signedMoney(daily.todayUsd)} valueTone={tone(daily.todayUsd)} />
        <Stat label="Rendement" value={percent(daily.todayPercentage)} valueTone={tone(daily.todayPercentage)} />
      </div>
      <PerformanceSparkline daily={daily} chart={chart} />
    </section>

    <section className="aps-performance-card">
      <header><div><small>HISTORIE</small><h3>Dagresultaten</h3></div><span>nieuwste → oudste</span></header>
      <div className="aps-performance-days">
        <div className="aps-performance-days-head"><span>Datum</span><span>Rendement</span><span>Winst/verlies</span><span>Eindwaarde</span></div>
        {rows.slice(0, visibleCount).map((row) => <div className="aps-performance-day-wrap" key={row.date}>
          <button type="button" className={`aps-performance-day${selectedDate === row.date ? " is-open" : ""}`} onClick={() => void selectDay(row)}>
            <span><b>{row.date === daily.referenceDate ? "Vandaag" : dateLabel(row.date, false)}</b><small>{row.date}</small></span>
            <strong className={`is-${tone(row.percentage)}`}>{percent(row.percentage)}</strong>
            <strong className={`is-${tone(row.usdChange)}`}>{signedMoney(row.usdChange)}</strong>
            <span className="aps-performance-end">{money(row.endEquity)}</span>
          </button>
          {selectedDate === row.date ? <DayDetails detail={detail} loading={detailLoading} /> : null}
        </div>)}
      </div>
      {rows.length > visibleCount ? <button type="button" className="aps-performance-more" onClick={() => setVisibleCount((current) => current + 7)}>Toon meer dagen <span>⌄</span></button> : null}
      {!rows.length ? <p className="aps-performance-note">Nog geen betrouwbare daghistorie beschikbaar.</p> : null}
    </section>

    <LedgerBreakdownView detail={daily} totalUsd={daily.todayUsd} totalPct={daily.todayPercentage} />
  </>;
}

function AnalysisTab({ daily }: { daily: DailyGrowth }) {
  const rows = useMemo(() => {
    const map = new Map<string, HistoryRow>();
    for (const row of daily.history || []) if (row?.date) map.set(row.date, row);
    const live = todayRow(daily);
    if (live) map.set(live.date, live);
    return [...map.values()].sort((a, b) => b.date.localeCompare(a.date));
  }, [daily]);
  const positive = rows.filter((row) => row.percentage > 0);
  const negative = rows.filter((row) => row.percentage < 0);
  const best = rows.length ? rows.reduce((a, b) => a.percentage >= b.percentage ? a : b) : null;
  const worst = rows.length ? rows.reduce((a, b) => a.percentage <= b.percentage ? a : b) : null;
  const winRate = positive.length + negative.length ? positive.length / (positive.length + negative.length) * 100 : null;

  return <>
    <section className="aps-performance-card">
      <header><div><small>ANALYSE</small><h3>Prestatie per periode</h3></div><span>{rows.length} dagen</span></header>
      <div className="aps-performance-analysis-grid">
        <Stat label="Vandaag" value={percent(rows[0]?.percentage)} valueTone={tone(rows[0]?.percentage)} />
        <Stat label="Gisteren" value={percent(rows[1]?.percentage)} valueTone={tone(rows[1]?.percentage)} />
        <Stat label="Laatste 7 dagen · gem." value={percent(average(rows.slice(0, 7)))} valueTone={tone(average(rows.slice(0, 7)))} />
        <Stat label="Laatste 30 dagen · gem." value={percent(average(rows.slice(0, 30)))} valueTone={tone(average(rows.slice(0, 30)))} />
        <Stat label="Sinds start · gem." value={percent(daily.averageDailyPercentage)} valueTone={tone(daily.averageDailyPercentage)} />
        <Stat label="Positieve dagen" value={String(positive.length)} valueTone="positive" />
        <Stat label="Negatieve dagen" value={String(negative.length)} valueTone="negative" />
        <Stat label="Dag-winrate" value={winRate === null ? "—" : `${winRate.toLocaleString("nl-NL", { maximumFractionDigits: 1 })}%`} />
      </div>
    </section>
    <section className="aps-performance-card">
      <header><div><small>UITSCHIETERS</small><h3>Beste &amp; slechtste dag</h3></div></header>
      <div className="aps-performance-extremes">
        <div><small>Beste dag</small><b>{best ? dateLabel(best.date) : "—"}</b><strong className="is-positive">{best ? percent(best.percentage) : "—"}</strong><span>{best ? signedMoney(best.usdChange) : "—"}</span></div>
        <div><small>Slechtste dag</small><b>{worst ? dateLabel(worst.date) : "—"}</b><strong className="is-negative">{worst ? percent(worst.percentage) : "—"}</strong><span>{worst ? signedMoney(worst.usdChange) : "—"}</span></div>
      </div>
    </section>
    <section className="aps-performance-card">
      <header><div><small>VANDAAG</small><h3>Bronnen van performance</h3></div></header>
      <LedgerBreakdownView detail={daily} totalUsd={daily.todayUsd} totalPct={daily.todayPercentage} compact />
    </section>
  </>;
}

function AverageTab({ daily }: { daily: DailyGrowth }) {
  const rows = useMemo(() => {
    const map = new Map<string, HistoryRow>();
    for (const row of daily.history || []) if (row?.date) map.set(row.date, row);
    const live = todayRow(daily);
    if (live) map.set(live.date, live);
    return [...map.values()].sort((a, b) => b.date.localeCompare(a.date));
  }, [daily]);
  const totalUsd = rows.reduce((sum, row) => sum + Number(row.usdChange || 0), 0);
  const avgUsd = rows.length ? totalUsd / rows.length : null;
  const positive = rows.filter((row) => row.percentage > 0).length;
  const negative = rows.filter((row) => row.percentage < 0).length;
  const best = rows.length ? rows.reduce((a, b) => a.percentage >= b.percentage ? a : b) : null;
  const worst = rows.length ? rows.reduce((a, b) => a.percentage <= b.percentage ? a : b) : null;

  return <>
    <section className="aps-performance-card aps-performance-average-hero">
      <small>GEMIDDELD RENDEMENT PER DAG</small>
      <strong className={`is-${tone(daily.averageDailyPercentage)}`}>{percent(daily.averageDailyPercentage)}</strong>
      <p>Vanaf {dateLabel(daily.measurementStartDate)} tot en met vandaag</p>
      <div className="aps-performance-analysis-grid">
        <Stat label="Gemiddeld US$ / dag" value={signedMoney(avgUsd)} valueTone={tone(avgUsd)} />
        <Stat label="Gemeten dagen" value={String(daily.measuredDays ?? rows.length || "—")} />
        <Stat label="Totaal tradingresultaat" value={signedMoney(totalUsd)} valueTone={tone(totalUsd)} />
        <Stat label="Startdatum" value={dateLabel(daily.measurementStartDate)} />
        <Stat label="Positieve dagen" value={String(positive)} valueTone="positive" />
        <Stat label="Negatieve dagen" value={String(negative)} valueTone="negative" />
        <Stat label="Beste dag" value={best ? percent(best.percentage) : "—"} valueTone="positive" detail={best ? dateLabel(best.date, false) : undefined} />
        <Stat label="Slechtste dag" value={worst ? percent(worst.percentage) : "—"} valueTone="negative" detail={worst ? dateLabel(worst.date, false) : undefined} />
      </div>
    </section>
    <section className="aps-performance-card aps-performance-formula">
      <header><div><small>BEREKENING</small><h3>Hoe ontstaat dit gemiddelde?</h3></div></header>
      <div className="aps-performance-formula-box">
        <span>som van alle betrouwbare, cashflow-gecorrigeerde dagpercentages</span>
        <i />
        <span>aantal gemeten dagen</span>
        <b>= {percent(daily.averageDailyPercentage)}</b>
      </div>
      <p>Dit is het rekenkundig gemiddelde dat de bestaande backend gebruikt. Vandaag telt mee; alleen dagen met een betrouwbare dagmeting worden opgenomen.</p>
    </section>
  </>;
}

function ExplanationTab({ daily }: { daily: DailyGrowth }) {
  const items = [
    ["Wat betekent Rendement vandaag?", "De verandering van de portfolio-equity sinds de betrouwbare dagstartmeting, nadat externe stortingen en opnames uit die verandering zijn gehaald."],
    ["Waarom telt een storting niet als winst?", "Een storting voegt kapitaal toe maar is geen tradingresultaat. De backend neutraliseert die cashflow daarom in het dagrendement."],
    ["Waarom telt een opname niet als verlies?", "Een opname verlaagt de accountwaarde, maar is geen tradingverlies. Ook die externe cashflow wordt uit het rendement gefilterd."],
    ["Wat is realized PnL?", "Het door Aster bevestigde resultaat dat in de REALIZED_PNL-ledger staat na het sluiten of verkleinen van posities."],
    ["Wat is open / unrealized PnL?", "Mark-to-market resultaat dat nog in open posities zit. Historisch bewaart de huidige dagmeting dit niet als losse component; daarom noemen we het verschil in de audit bewust equity-rest en niet automatisch zuivere unrealized PnL."],
    ["Hoe worden funding, fees en liquidaties behandeld?", "Die zijn tradingeffecten en blijven in de performance. Alleen echte externe cashflows worden geneutraliseerd. Liquidatie/ADL-effecten worden dus niet uit het rendement weggefilterd."],
    ["Wat is Gemiddeld per dag?", `Het rekenkundig gemiddelde van alle betrouwbare dagelijkse rendementen. Deze accountmeting bevat momenteel ${daily.measuredDays ?? "—"} gemeten dagen sinds ${dateLabel(daily.measurementStartDate)}.`],
  ];
  return <section className="aps-performance-card aps-performance-explanation">
    <header><div><small>UITLEG</small><h3>Zo leest u het rendement</h3></div><span>ⓘ</span></header>
    {items.map(([title, body]) => <details key={title} open={title === items[0][0]}><summary>{title}</summary><p>{body}</p></details>)}
    <div className="aps-performance-method"><small>ACTIEVE BEREKENINGSMETHODE</small><b>{daily.performanceMethod || "SAME_DAY_SNAPSHOT_NET_CASHFLOW_ADJUSTED"}</b><span>Daggrens: Europe/Amsterdam</span></div>
  </section>;
}

export function PortfolioPerformanceDetail({ initialTab = "per-day", onBack }: { initialTab?: PerformanceInitialTab; onBack: () => void }) {
  const [tab, setTab] = useState<PerformanceInitialTab>(initialTab);
  const [daily, setDaily] = useState<DailyGrowth | null>(null);
  const [chart, setChart] = useState<ChartPayload | null>(null);
  const [error, setError] = useState("");
  const [closing, setClosing] = useState(false);

  useEffect(() => setTab(initialTab), [initialTab]);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      setError("");
      try {
        const [dailyPayload, chartPayload] = await Promise.all([
          authenticatedRequest("/api/exchanges/aster/portfolio-growth/daily", { cache: "no-store" }) as Promise<DailyGrowth>,
          authenticatedRequest("/api/exchanges/aster/portfolio-chart?timeframe=5m&limit=320", { cache: "no-store" }) as Promise<ChartPayload>,
        ]);
        if (!alive) return;
        setDaily(dailyPayload);
        setChart(chartPayload);
      } catch (cause) {
        if (alive) setError(cause instanceof Error ? cause.message : "Rendementsoverzicht kon niet worden geladen.");
      }
    };
    void load();
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const close = () => {
    if (closing) return;
    setClosing(true);
    window.setTimeout(onBack, 300);
  };

  return <section className={`aps-detail-page aps-performance-page${closing ? " is-closing" : ""}`} aria-label="Rendement Overzicht">
    <button type="button" className="aps-detail-back" onClick={close}><span aria-hidden="true">←</span><b>Terug naar Portfolio Snapshot</b></button>
    <div className="aps-detail-page-title aps-performance-title">
      <span className="aps-detail-page-icon" aria-hidden="true">↗</span>
      <div><h2>Rendement Overzicht</h2><p>Auditbaar dagrendement · cashflow-gecorrigeerd · Europe/Amsterdam</p></div>
    </div>
    <nav className="aps-performance-tabs" aria-label="Rendement tabs">
      {TABS.map((item) => <button key={item.id} type="button" className={tab === item.id ? "is-active" : ""} onClick={() => setTab(item.id)}>{item.label}</button>)}
    </nav>

    {error ? <div className="aps-performance-error"><b>Rendement niet beschikbaar</b><span>{error}</span></div> : null}
    {!error && !daily ? <div className="aps-performance-loading">Rendementsoverzicht laden…</div> : null}
    {daily && !daily.reliable ? <div className="aps-performance-error"><b>Berekening tijdelijk niet betrouwbaar</b><span>{daily.blockReason || "De backend heeft de dagmeting fail-closed verborgen."}</span></div> : null}
    {daily?.reliable ? <div className="aps-performance-content">
      {tab === "per-day" ? <DailyTab daily={daily} chart={chart} /> : null}
      {tab === "analysis" ? <AnalysisTab daily={daily} /> : null}
      {tab === "average" ? <AverageTab daily={daily} /> : null}
      {tab === "explanation" ? <ExplanationTab daily={daily} /> : null}
    </div> : null}
  </section>;
}
