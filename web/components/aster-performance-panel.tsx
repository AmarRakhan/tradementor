"use client";

import { useMemo, useState } from "react";
import { realizedCalendar, type RealizedTrade } from "@/lib/realized-calendar";
import { AsterStrategy2Behavior } from "@/components/aster-strategy2-behavior";
import { AsterStrategy3Control } from "@/components/aster-strategy3-control";
import { AsterUniverseStatus } from "@/components/aster-universe-status";

function n(v: unknown) { const x = Number(v); return Number.isFinite(x) ? x : 0; }
function usd(v: number) { return new Intl.NumberFormat("nl-NL", { style: "currency", currency: "USD" }).format(v); }
type EquityDay = { date: string; start: number; end: number; changePct: number | null };

function localDay(value: number) {
  const date = new Date(value);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function asterEquityDays(currentEquity: number): Map<string, EquityDay> {
  if (typeof window === "undefined") return new Map();
  try {
    const raw = JSON.parse(window.localStorage.getItem("tradementor.test.portfolioEquity.v1") || "[]");
    const rows = (Array.isArray(raw) ? raw : [])
      .map((row) => ({ at: Number(row?.at), value: Number(row?.aster) }))
      .filter((row) => Number.isFinite(row.at) && Number.isFinite(row.value) && row.value > 0)
      .sort((left, right) => left.at - right.at);
    if (currentEquity > 0) rows.push({ at: Date.now(), value: currentEquity });
    const grouped = new Map<string, Array<{ at: number; value: number }>>();
    for (const row of rows) {
      const date = localDay(row.at);
      grouped.set(date, [...(grouped.get(date) || []), row]);
    }
    return new Map([...grouped].map(([date, values]) => {
      const start = values[0]?.value || 0;
      const end = values[values.length - 1]?.value || 0;
      return [date, { date, start, end, changePct: values.length > 1 && start > 0 ? ((end - start) / start) * 100 : null }];
    }));
  } catch { return new Map(); }
}

function signedPercent(value: number | null) {
  if (value === null) return "Portefeuille —";
  return `Portefeuille ${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function AsterPerformancePanel({ snapshot, onChanged }: { snapshot: Record<string, unknown> | null; onChanged: () => void }) {
  const equity = n(snapshot?.equity);
  const unrealized = n(snapshot?.unrealizedPnl);
  const s2 = (snapshot?.strategy2 && typeof snapshot.strategy2 === "object" ? snapshot.strategy2 : {}) as Record<string, unknown>;
  const s3 = (snapshot?.strategy3 && typeof snapshot.strategy3 === "object" ? snapshot.strategy3 : {}) as Record<string, unknown>;
  const performance = (s2.performance && typeof s2.performance === "object" ? s2.performance : {}) as Record<string, unknown>;
  const hwm = n(performance.highWaterMark) || equity;
  const drawdown = hwm > 0 ? Math.max(0, (hwm - equity) / hwm) : 0;
  const ledger = Array.isArray(snapshot?.realizedEvents) ? snapshot.realizedEvents : [];
  const trades = (ledger.length ? ledger : Array.isArray(snapshot?.closedTrades) ? snapshot.closedTrades : []) as RealizedTrade[];
  const historyAvailable = snapshot?.historyAvailable === true;
  const calendar = useMemo(() => realizedCalendar(trades), [trades]);
  const equityDays = useMemo(() => asterEquityDays(equity), [equity, snapshot?.updatedAt]);
  const visibleDays = useMemo(() => {
    const days = [...calendar.days];
    if (!days.some((day) => day.date === calendar.today.date)) days.push(calendar.today);
    return days.sort((left, right) => left.date.localeCompare(right.date)).slice(-35);
  }, [calendar]);
  const [selectedDate, setSelectedDate] = useState("");
  const selected = visibleDays.find((day) => day.date === selectedDate) ?? calendar.today;

  return <section className="aster-performance">
    <div className="performance-head"><div><span className="kicker">ASTER PERFORMANCE</span><h2>Portfolio en strategie-eenheid</h2></div><span className="truth-badge">Exchange-confirmed closes</span></div>
    <div className="performance-metrics"><P label="Portfolio Equity" value={usd(equity)} /><P label="High-Water Mark" value={usd(hwm)} /><P label="Current Drawdown" value={`${(drawdown * 100).toFixed(2)}%`} /><P label="Vandaag gesloten" value={historyAvailable ? usd(calendar.today.total) : "—"} /><P label="Unrealized PnL" value={usd(unrealized)} /><P label="Strategy 2" value={String(s2.phase || "DRAFT")} /></div>
    <div className="strategy-performance-grid"><article><b>Strategy 1 · Profit Harvest Hedge</b><span>Actieve engine blijft afzonderlijk geattribueerd.</span><small>Open PnL en equity blijven onderdeel van het echte resultaat.</small></article><article><b>Strategy 2 · Dual Profit Harvest</b><span>{s2.enabled ? "Engine actief" : "Nog niet gestart"} · Live {s2.liveReady ? "ready" : "locked"}</span><small>LONG en SHORT worden als zelfstandige harvestcycles gevolgd.</small></article></div>
    <AsterUniverseStatus value={snapshot?.automationUniverse} />
    <AsterUniverseStatus value={s2.universe} />
    <AsterUniverseStatus value={s3.universe} />
    <AsterStrategy2Behavior snapshot={snapshot} />
    <AsterStrategy3Control snapshot={snapshot} onChanged={onChanged} />
    <div className="performance-calendar realized-calendar"><div><b>Kalender gesloten resultaat</b><small>Lokale kalenderdag · tik voor details</small></div>{historyAvailable ? <><div className="calendar-days">{visibleDays.map((day) => { const change = equityDays.get(day.date)?.changePct ?? null; return <button type="button" key={day.date} className={`${day.total > 0 ? "gain" : day.total < 0 ? "loss" : "flat"} ${selected.date === day.date ? "selected" : ""}`} onClick={() => setSelectedDate(day.date)}><span>{day.date.slice(5)}</span><b>{day.total >= 0 ? "+" : ""}{usd(day.total)}</b><small className={`portfolio-day-change ${change === null ? "unknown" : change >= 0 ? "profit" : "loss"}`}>{signedPercent(change)}</small><small>{day.trades} sluitingen</small></button>; })}</div><article className="calendar-day-detail"><div><span>Geselecteerde dag</span><strong>{selected.date}</strong></div><div><span>Werkelijk gesloten resultaat</span><strong className={selected.total >= 0 ? "profit" : "loss"}>{selected.total >= 0 ? "+" : ""}{usd(selected.total)}</strong></div><div><span>Portfoliowaarde die dag</span><strong className={(equityDays.get(selected.date)?.changePct ?? 0) >= 0 ? "profit" : "loss"}>{signedPercent(equityDays.get(selected.date)?.changePct ?? null).replace("Portefeuille ", "")}</strong></div><div><span>Sluitingen</span><strong>{selected.trades}</strong></div><div><span>Winst / verlies</span><strong>{selected.wins} / {selected.losses}</strong></div></article><p>Gesloten resultaat komt uitsluitend uit Asters bevestigde REALIZED_PNL-administratie. Het portefeuillepercentage vergelijkt de eerste en laatste betrouwbare Aster-equitymeting van die lokale kalenderdag; bij onvoldoende metingen tonen we geen percentage.</p></> : <p>Aster heeft de gerealiseerde geschiedenis nog niet betrouwbaar bevestigd. Daarom tonen we geen misleidende nulwaarde.</p>}</div>
  </section>;
}

function P({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }
