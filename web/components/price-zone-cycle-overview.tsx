"use client";

import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

const REFERENCE = "file_00000000773c8210ad977be9527738e6";

type Dict = Record<string, unknown>;
type OpenCounts = Record<string, { long: number; short: number; total: number }>;

type SeatTruth = {
  activeZone: number | null;
  perZoneLong: number;
  perZoneShort: number;
  strategyOpenTotal: number;
  zoneOpenCounts: OpenCounts;
  zoneOpenCountsReliable: boolean;
  openKeys: Set<string>;
};

type SeatSummaryProp = {
  activeZone: number | null;
  perZoneLong: number;
  perZoneShort: number;
  strategyOpenTotal: number;
  zoneOpenCounts: OpenCounts;
  zoneOpenCountsReliable: boolean;
  openZonePositionKeys: string[];
  currentPrice: number | null;
  nextLongLevels: {
    status: string;
    up: { zone: number; price: number; distance: number; freeLongSeats: number; unit: string; entryPermission: string } | null;
    down: { zone: number; price: number; distance: number; freeLongSeats: number; unit: string; entryPermission: string } | null;
  } | null;
  zones: Array<ZoneLevel & {
    longOpen: number;
    shortOpen: number;
    totalOpen: number;
    longMax: number;
    shortMax: number;
    totalMax: number;
    active: boolean;
  }>;
  otherOpenPositions: Array<{ positionKey: string; symbol: string; side: string; ownerType: string; role: string; reason: string }>;
  unassignedStrategyPositions: Array<{ positionKey: string; symbol: string; side: string; role: string; originZone: number | null; reason: string }>;
  reconciliation: {
    accountMatches: boolean;
    strategyMatches: boolean;
    zonesMatchStrategy: boolean;
    accountTotal: number;
    strategyTotal: number;
    zoneAssignedTotal: number;
    unassignedStrategyTotal: number;
    otherOpenTotal: number;
  };
};

type ZoneLevel = { index: number; center: number | null; lower: number | null; upper: number | null };
type ZoneEntry = {
  symbol: string;
  side: "LONG" | "SHORT" | "";
  atMs: number;
  activityType: string;
  originZone: number | null;
  soldierRole: string;
};
type ZoneTrade = {
  symbol: string;
  side: "LONG" | "SHORT" | "";
  atMs: number;
  activityType: string;
  originZone: number | null;
  soldierRole: string;
  realizedPnlUsd: number | null;
};
type Marker = { atMs: number; entries: ZoneEntry[]; trades: ZoneTrade[] };
type ChartTruth = {
  currentEquity: number | null;
  currentZone: number | null;
  zones: ZoneLevel[];
  markers: Marker[];
};

type CycleEvent = {
  atMs: number;
  kind: "entry" | "close";
  key: string;
  originZone: number;
  pnl: number | null;
  activityType: string;
};

type CycleTruth = {
  reliable: boolean;
  start: CycleEvent | null;
  visited: Set<number>;
  profits: Map<number, { count: number; pnl: number; pnlReliable: boolean; lastAtMs: number }>;
  lastProfit: CycleEvent | null;
  totalProfits: number | null;
  totalPnl: number | null;
};

const rec = (value: unknown): Dict => value && typeof value === "object" && !Array.isArray(value) ? value as Dict : {};
const num = (value: unknown): number | null => {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};
const int = (value: unknown): number | null => {
  const parsed = num(value);
  return parsed !== null && Number.isInteger(parsed) ? parsed : null;
};
const stamp = (value: unknown): number => {
  const numeric = num(value);
  if (numeric !== null) return numeric > 0 && numeric < 10_000_000_000 ? numeric * 1000 : numeric;
  if (typeof value !== "string" || !value.trim()) return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
};
const zoneLabel = (value: number) => value > 0 ? `+${value}` : String(value);
const priceLabel = (value: number | null) => {
  if (value === null || !Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  const digits = abs >= 10 ? 2 : abs >= 1 ? 3 : 5;
  return new Intl.NumberFormat("nl-NL", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
};
const validZoneRange = (zone: ZoneLevel | undefined): boolean =>
  Boolean(zone && zone.lower !== null && zone.upper !== null &&
    Number.isFinite(zone.lower) && Number.isFinite(zone.upper) &&
    zone.lower > 0 && zone.upper > zone.lower);

const priceRangeLabel = (zone: ZoneLevel | undefined) =>
  validZoneRange(zone) && zone
    ? `${priceLabel(zone.lower)} - ${priceLabel(zone.upper)}`
    : "—";
const clockLabel = (value: number | null) => {
  if (!value) return "—";
  const date = new Date(value);
  const key = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Amsterdam", year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Amsterdam", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  const time = new Intl.DateTimeFormat("nl-NL", { timeZone: "Europe/Amsterdam", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(date);
  if (key === today) return `Vandaag ${time}`;
  return new Intl.DateTimeFormat("nl-NL", { timeZone: "Europe/Amsterdam", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(date);
};

function chartTruthFrom(eventPayload: unknown, seatSummary: SeatSummaryProp | null): ChartTruth {
  const events = rec(eventPayload);
  const zones: ZoneLevel[] = (seatSummary?.zones ?? []).map((row) => ({
    index: row.index,
    center: row.center,
    lower: row.lower,
    upper: row.upper,
  })).filter((row) => row.center !== null && row.center > 0);

  const markers: Marker[] = [];
  for (const raw of Array.isArray(events.markers) ? events.markers : []) {
    const marker = rec(raw);
    const markerAt = stamp(marker.atMs);
    const entries: ZoneEntry[] = [];
    const trades: ZoneTrade[] = [];
    for (const item of Array.isArray(marker.entries) ? marker.entries : []) {
      const row = rec(item);
      const sideRaw = String(row.side || "").toUpperCase();
      entries.push({
        symbol: String(row.symbol || "").toUpperCase(),
        side: sideRaw === "LONG" || sideRaw === "SHORT" ? sideRaw : "",
        atMs: stamp(row.atMs) || markerAt,
        activityType: String(row.activityType || "").toUpperCase(),
        originZone: int(row.originZone),
        soldierRole: String(row.soldierRole || "").toUpperCase(),
      });
    }
    for (const item of Array.isArray(marker.trades) ? marker.trades : []) {
      const row = rec(item);
      const sideRaw = String(row.side || "").toUpperCase();
      trades.push({
        symbol: String(row.symbol || "").toUpperCase(),
        side: sideRaw === "LONG" || sideRaw === "SHORT" ? sideRaw : "",
        atMs: stamp(row.atMs) || markerAt,
        activityType: String(row.activityType || "").toUpperCase(),
        originZone: int(row.originZone),
        soldierRole: String(row.soldierRole || "").toUpperCase(),
        realizedPnlUsd: num(row.realizedPnlUsd),
      });
    }
    markers.push({ atMs: markerAt, entries, trades });
  }
  markers.sort((a, b) => a.atMs - b.atMs);
  return {
    currentEquity: seatSummary?.currentPrice ?? null,
    currentZone: seatSummary?.activeZone ?? null,
    zones,
    markers,
  };
}

function deriveCycle(seats: SeatTruth, chart: ChartTruth): CycleTruth {
  const events: CycleEvent[] = [];
  for (const marker of chart.markers) {
    for (const entry of marker.entries) {
      if (!entry.symbol || !entry.side || entry.originZone === null) continue;
      if (entry.soldierRole && entry.soldierRole !== "ZONE_BASE" && entry.soldierRole !== "EXPOSURE_BALANCER") continue;
      if (entry.activityType === "DCA" || entry.activityType === "ADD" || entry.activityType === "MANUAL_DCA_DETECTED") continue;
      events.push({
        atMs: entry.atMs,
        kind: "entry",
        key: `${entry.symbol}|${entry.side}`,
        originZone: entry.originZone,
        pnl: null,
        activityType: entry.activityType,
      });
    }
    for (const trade of marker.trades) {
      if (!trade.symbol || !trade.side || trade.originZone === null) continue;
      if (trade.soldierRole && trade.soldierRole !== "ZONE_BASE" && trade.soldierRole !== "EXPOSURE_BALANCER") continue;
      if (trade.activityType === "PARTIAL_TP") continue;
      events.push({
        atMs: trade.atMs,
        kind: "close",
        key: `${trade.symbol}|${trade.side}`,
        originZone: trade.originZone,
        pnl: trade.realizedPnlUsd,
        activityType: trade.activityType,
      });
    }
  }
  events.sort((a, b) => a.atMs - b.atMs);

  let start: CycleEvent | null = null;
  if (seats.strategyOpenTotal > 0 && seats.openKeys.size === seats.strategyOpenTotal) {
    const active = new Set(seats.openKeys);
    for (let index = events.length - 1; index >= 0; index -= 1) {
      const event = events[index];
      if (event.kind === "close") active.add(event.key);
      else {
        active.delete(event.key);
        if (active.size === 0) {
          start = event;
          break;
        }
      }
    }
  }

  const reliable = start !== null;
  const visited = new Set<number>();
  for (const key of Object.keys(seats.zoneOpenCounts)) {
    const zone = int(key);
    if (zone !== null && (seats.zoneOpenCounts[key]?.total ?? 0) > 0) visited.add(zone);
  }
  const profits = new Map<number, { count: number; pnl: number; pnlReliable: boolean; lastAtMs: number }>();
  const cycleEvents = reliable ? events.filter((event) => event.atMs >= start!.atMs) : [];
  for (const event of cycleEvents) {
    visited.add(event.originZone);
    if (event.kind !== "close") continue;
    const bucket = profits.get(event.originZone) ?? { count: 0, pnl: 0, pnlReliable: true, lastAtMs: 0 };
    bucket.count += 1;
    // MULTI_BB_TP is confirmed profitable by execution semantics, but older
    // audit rows may not carry exact realized PnL. Never turn unknown money into 0.
    if (event.pnl === null || !Number.isFinite(event.pnl) || event.pnl <= 0) bucket.pnlReliable = false;
    else bucket.pnl += event.pnl;
    bucket.lastAtMs = Math.max(bucket.lastAtMs, event.atMs);
    profits.set(event.originZone, bucket);
  }
  const closeEvents = cycleEvents.filter((event) => event.kind === "close");
  const lastProfit = closeEvents.length ? closeEvents[closeEvents.length - 1] : null;
  const totalProfits = reliable ? [...profits.values()].reduce((sum, row) => sum + row.count, 0) : null;
  const pnlReliable = reliable && [...profits.values()].every((row) => row.pnlReliable);
  const totalPnl = pnlReliable ? [...profits.values()].reduce((sum, row) => sum + row.pnl, 0) : null;
  return { reliable, start, visited, profits, lastProfit, totalProfits, totalPnl };
}

function visibleZoneIndexes(seats: SeatTruth, chart: ChartTruth, cycle: CycleTruth): number[] {
  const active = seats.activeZone ?? chart.currentZone;
  const known = new Set<number>();
  for (const zone of chart.zones) known.add(zone.index);
  for (const raw of Object.keys(seats.zoneOpenCounts)) {
    const zone = int(raw);
    if (zone !== null) known.add(zone);
  }
  for (const zone of cycle.visited) known.add(zone);
  if (active !== null) {
    for (let zone = active - 5; zone <= active + 5; zone += 1) known.add(zone);
  }
  let rows = [...known].sort((a, b) => b - a);
  if (rows.length > 25 && active !== null) {
    rows = rows.sort((a, b) => Math.abs(a - active) - Math.abs(b - active)).slice(0, 25).sort((a, b) => b - a);
  } else if (rows.length > 25) rows = rows.slice(0, 25);
  return rows;
}

export function PriceZoneCycleOverview({
  seatSummary,
  liveActiveZone,
}: {
  seatSummary: SeatSummaryProp | null;
  liveActiveZone: number | null;
}) {
  const [chartTruth, setChartTruth] = useState<ChartTruth | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadWarning, setLoadWarning] = useState("");

  const seatTruth = useMemo<SeatTruth | null>(() => seatSummary ? {
    activeZone: seatSummary.activeZone,
    perZoneLong: seatSummary.perZoneLong,
    perZoneShort: seatSummary.perZoneShort,
    strategyOpenTotal: seatSummary.strategyOpenTotal,
    zoneOpenCounts: seatSummary.zoneOpenCounts,
    zoneOpenCountsReliable: seatSummary.zoneOpenCountsReliable,
    openKeys: new Set(seatSummary.openZonePositionKeys),
  } : null, [seatSummary]);

  useEffect(() => {
    let alive = true;
    let refreshBusy = false;
    const refresh = async () => {
      if (refreshBusy) return;
      refreshBusy = true;
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 8000);
      try {
        const events = await authenticatedRequest("/api/exchanges/aster/portfolio-chart/events?timeframe=15m", { cache: "no-store", signal: controller.signal });
        if (!alive) return;
        setChartTruth(chartTruthFrom(events, seatSummary));
        setLoadWarning("");
      } catch {
        if (!alive) return;
        setChartTruth((current) => chartTruthFrom({ markers: current?.markers ?? [] }, seatSummary));
        setLoadWarning("Cyclus-events worden tijdelijk niet bijgewerkt.");
      } finally {
        window.clearTimeout(timeout);
        refreshBusy = false;
        if (alive) setLoading(false);
      }
    };
    void refresh();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 5000);
    const visible = () => { if (document.visibilityState === "visible") void refresh(); };
    document.addEventListener("visibilitychange", visible);
    return () => {
      alive = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [seatSummary]);

  const derived = useMemo(() => {
    if (!seatTruth) return null;
    const safeChart = chartTruth ?? { currentEquity: null, currentZone: null, zones: [], markers: [] };
    const cycle = deriveCycle(seatTruth, safeChart);
    return { cycle, indexes: visibleZoneIndexes(seatTruth, safeChart, cycle) };
  }, [seatTruth, chartTruth]);

  const activeZone = seatTruth?.activeZone ?? liveActiveZone ?? null;
  const centerByZone = new Map((seatSummary?.zones ?? []).map((zone) => [zone.index, zone.center]));
  const levelByZone = new Map((seatSummary?.zones ?? []).map((zone) => [zone.index, {
    index: zone.index,
    center: zone.center,
    lower: zone.lower,
    upper: zone.upper,
  } as ZoneLevel]));
  const cycle = derived?.cycle ?? null;
  const startZone = cycle?.start?.originZone ?? null;
  const lastZone = cycle?.lastProfit?.originZone ?? null;

  return (
    <section className="aps-zone-cycle-overview" data-reference={REFERENCE} aria-label="Zone overzicht huidige cyclus">
      <header className="aps-zco-head">
        <div>
          <h3>Zone overzicht <small>(huidige cyclus)</small></h3>
          <p>Realtime status van alle prijszones.</p>
        </div>
        <div className="aps-zco-view" aria-label="Weergave alle zones">
          <small>Weergave</small>
          <span>Alle zones <b aria-hidden="true">⌄</b></span>
        </div>
      </header>
      <div className="aps-zco-compact-summary" aria-label="Volgende vrije LONG-capaciteit en actuele zone" style={{ display: "grid", gridTemplateColumns: "minmax(0,.8fr) repeat(2,minmax(0,1fr)) minmax(0,1.15fr) minmax(0,.85fr)", gap: 0, alignItems: "center", margin: "10px 0 12px", padding: "8px 4px", border: "1px solid rgba(55,160,99,.28)", borderRadius: 12, background: "rgba(2,24,12,.5)" }}>
        <span style={{ padding: "0 5px", color: "#77dfab", fontSize: 12, lineHeight: 1.25 }}>Volgende<br />LONG</span>
        {(["up", "down"] as const).map((direction) => {
          const level = seatSummary?.nextLongLevels?.status === "AVAILABLE" ? seatSummary.nextLongLevels[direction] : null;
          const distance = level?.distance ?? null;
          const validDistance = distance !== null && Number.isFinite(distance) && distance > 0;
          const color = direction === "up" ? "#6af1ad" : "#ff829e";
          return <span key={direction} style={{ minWidth: 0, borderLeft: "1px solid rgba(70,132,87,.3)", padding: "0 5px", color }} title={level ? `Zone ${zoneLabel(level.zone)} · ${level.freeLongSeats} vrije LONG-stoelen; alleen zonecapaciteit, geen ordertoestemming` : "Geen betrouwbare volgende LONG-zone"}>
            <small style={{ display: "block", fontSize: 10, lineHeight: 1.3 }}>{direction === "up" ? "↑ Omhoog" : "↓ Omlaag"}</small>
            <b style={{ display: "block", fontSize: 12, whiteSpace: "nowrap", letterSpacing: "-.25px", fontVariantNumeric: "tabular-nums" }}>{validDistance ? `$ ${priceLabel(distance)}` : "—"}</b>
          </span>;
        })}
        <span style={{ minWidth: 0, borderLeft: "1px solid rgba(70,132,87,.3)", padding: "0 5px" }}><small style={{ display: "block", fontSize: 10, whiteSpace: "nowrap" }}>Huidige prijs</small><b style={{ fontSize: 11, whiteSpace: "nowrap" }}>{seatSummary?.currentPrice === null || seatSummary?.currentPrice === undefined ? "—" : `$ ${priceLabel(seatSummary.currentPrice)}`}</b></span>
        <span style={{ minWidth: 0, borderLeft: "1px solid rgba(70,132,87,.3)", padding: "0 5px", textAlign: "center" }}><small style={{ display: "block", fontSize: 10 }}>Actieve zone</small><b style={{ display: "block", color: "#f6c965", fontSize: 12 }}>{activeZone === null ? "—" : zoneLabel(activeZone)}</b></span>
      </div>

      {seatSummary && seatSummary.zones.some((zone) => !validZoneRange(zone)) ? (
        <p className="aps-zco-truth-note" role="status">ⓘ Canonical prijsgrenzen ontbreken voor één of meer zones. De ontbrekende data moet in de server-ladder worden hersteld.</p>
      ) : null}
      <div className="aps-zco-table-wrap" aria-busy={false}>
        <table className="aps-zco-table">
          <thead>
            <tr>
              <th>Zone</th>
              <th>Prijsrange<small>(USDT)</small></th>
              <th className="long">LONG<small>open / max</small></th>
              <th className="short">SHORT<small>open / max</small></th>
              <th>Totaal<small>bezet</small></th>
            </tr>
          </thead>
          <tbody>
            {(derived?.indexes ?? []).map((zone) => {
              const open = seatTruth?.zoneOpenCountsReliable ? (seatTruth.zoneOpenCounts[String(zone)] ?? { long: 0, short: 0, total: 0 }) : null;
              const capacity = seatTruth ? seatTruth.perZoneLong + seatTruth.perZoneShort : null;
              const full = Boolean(open && capacity !== null && capacity > 0 && open.long >= (seatTruth?.perZoneLong ?? 0) && open.short >= (seatTruth?.perZoneShort ?? 0));
              const isActive = activeZone === zone;
              const hasOpen = Boolean(open && open.total > 0);
              const visited = Boolean(cycle?.visited.has(zone));
              return (
                <tr key={zone} className={[isActive ? "is-active" : "", full ? "is-full" : "", hasOpen ? "has-open" : "", visited ? "is-visited" : ""].filter(Boolean).join(" ")}>
                  <td className="zone-cell">{isActive ? <i aria-hidden="true">›</i> : null}<b>{zoneLabel(zone)}</b>{startZone === zone ? <em title="Eerste entry deze cyclus">◎</em> : null}</td>
                  <td title={validZoneRange(levelByZone.get(zone)) ? undefined : "Canonical prijsgrenzen ontbreken of zijn ongeldig"}>{priceRangeLabel(levelByZone.get(zone))}</td>
                  <td className="long">{open && seatTruth ? `${open.long} / ${seatTruth.perZoneLong}` : "— / —"}</td>
                  <td className="short">{open && seatTruth ? `${open.short} / ${seatTruth.perZoneShort}` : "— / —"}</td>
                  <td>{open && capacity !== null ? `${open.total} / ${capacity}` : "— / —"}</td>
                </tr>
              );
            })}
            {!derived?.indexes.length ? <tr><td colSpan={5} className="empty">{loading ? "Zonegegevens worden geladen…" : "Geen betrouwbare zonegegevens beschikbaar."}</td></tr> : null}
          </tbody>
        </table>
      </div>

      {seatSummary && (seatSummary.reconciliation.otherOpenTotal > 0 || seatSummary.reconciliation.unassignedStrategyTotal > 0) ? (
        <p className="aps-zco-truth-note">
          ⓘ Account {seatSummary.reconciliation.accountTotal} = Strategy 2 {seatSummary.reconciliation.strategyTotal}
          {seatSummary.reconciliation.otherOpenTotal > 0 ? ` + overig ${seatSummary.reconciliation.otherOpenTotal}` : ""}
          {seatSummary.otherOpenPositions.length ? ` · ${seatSummary.otherOpenPositions.map((row) => `${row.symbol} ${row.side}`).join(", ")}` : ""}
          {seatSummary.unassignedStrategyPositions.length ? ` · niet aan zone toegewezen: ${seatSummary.unassignedStrategyPositions.map((row) => `${row.symbol} ${row.side}`).join(", ")}` : ""}
        </p>
      ) : null}

      <div className="aps-zco-cards">
        <article>
          <span className="icon" aria-hidden="true">◷</span>
          <div><small>Eerste entry deze cyclus</small><b>{cycle?.start ? `Zone ${zoneLabel(cycle.start.originZone)} @ ${priceLabel(centerByZone.get(cycle.start.originZone) ?? null)}` : "—"}</b><em>{clockLabel(cycle?.start?.atMs ?? null)}</em></div>
        </article>
        <article>
          <span className="icon" aria-hidden="true">🏆</span>
          <div><small>Laatste profit</small><b>{cycle?.lastProfit ? `Zone ${zoneLabel(cycle.lastProfit.originZone)} @ ${priceLabel(centerByZone.get(cycle.lastProfit.originZone) ?? null)}` : cycle?.reliable ? "Nog geen profit deze cyclus" : "—"}</b><em>{clockLabel(cycle?.lastProfit?.atMs ?? null)}</em></div>
        </article>
        <article>
          <span className="icon" aria-hidden="true">🏆</span>
          <div><small>Totaal profits deze cyclus</small><b className="profit-count">{cycle?.totalProfits ?? "—"}</b><em className="money">{cycle?.totalPnl === null || cycle?.totalPnl === undefined ? "—" : `+ US$ ${priceLabel(cycle.totalPnl)}`}</em></div>
        </article>
      </div>

      <div className="aps-zco-legend" aria-label="Legenda">
        <span><i className="gold"/>Actieve zone</span>
        <span><i className="green"/>Zone met open posities</span>
        <span><i className="red"/>Volledig bezet</span>
        <span><i className="grey"/>Toekomstige zone</span>
        <span><b>◎</b>Eerste entry</span>
        <span><b>🏆</b>Profit in zone</span>
        <span><b>›</b>Huidige prijs</span>
      </div>

      {loadWarning ? <p className="aps-zco-truth-note">ⓘ {loadWarning}</p> : null}
      {cycle && !cycle.reliable && (seatTruth?.strategyOpenTotal ?? 0) > 0 ? (
        <p className="aps-zco-truth-note">ⓘ De cyclusstart kan met de beschikbare bevestigde eventhistorie nog niet volledig worden bewezen. Onbekende waarden blijven daarom bewust op —.</p>
      ) : null}
    </section>
  );
}
