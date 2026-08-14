"use client";

import { useState } from "react";
import { parseAsterBotStatus, type StrategyDashboardStatus } from "@/lib/aster-bot-status";

const runtimeLabel: Record<string, string> = { LIVE: "ACTIEF", PAPER: "PAPER", STOPPED: "UIT", BLOCKED: "GEBLOKKEERD", RECOVERING: "HERSTEL", UNKNOWN: "ONBEKEND" };
const entryLabel: Record<string, string> = { ALLOWED: "NIEUWE INSTAPPERS TOEGESTAAN", WAITING: "NIEUWE INSTAPPERS WACHTEN", BLOCKED: "NIEUWE INSTAPPERS GEBLOKKEERD", UNKNOWN: "INSTAPSTATUS ONBEKEND" };
const gateLabel: Record<string, string> = { asterLiveExecution: "Aster live-poort", strategyLive: "Strategie live-poort", runtimeEnabled: "Runtimepoort", canaryValidated: "Canary", liveReady: "liveReady" };

function time(value: unknown) {
  const date = new Date(String(value || ""));
  return Number.isFinite(date.getTime()) ? date.toLocaleString("nl-NL", { dateStyle: "short", timeStyle: "medium" }) : "Niet bewezen";
}

function StrategyDetail({ id, value }: { id: 2 | 3; value: StrategyDashboardStatus }) {
  return <section className="bot-strategy-detail" aria-label={`Strategy ${id} details`}>
    <dl><div><dt>Modus</dt><dd>{value.mode}</dd></div><div><dt>Fase</dt><dd>{value.phase}</dd></div><div><dt>Scheduler</dt><dd>{value.schedulerStatus.status}</dd></div><div><dt>Eigen posities</dt><dd>{value.ownedPositions}</dd></div><div><dt>Ownership</dt><dd>{value.ownershipStatus}</dd></div><div><dt>Laatste controle</dt><dd>{time(value.lastTickAt)}</dd></div></dl>
    <div className="bot-gates">{Object.entries(value.liveGates).map(([key, enabled]) => <span className={enabled ? "pass" : "fail"} key={key}>{enabled ? "✓" : "×"} {gateLabel[key] || key}</span>)}</div>
    <p><b>Laatste bewezen actie</b>{value.lastAction === "NIET_BEWEZEN" ? "Niet bewezen" : value.lastAction}</p>
    <p><b>Laatste reden</b>{value.lastReason}</p>
    {value.schedulerStatus.warning && <p className="bot-detail-warning"><b>Schedulerwaarschuwing</b>{value.schedulerStatus.warning}</p>}
  </section>;
}

export function AsterBotStatus({ snapshot }: { snapshot: Record<string, unknown> | null }) {
  const [open, setOpen] = useState<2 | 3 | null>(null);
  const value = parseAsterBotStatus(snapshot);
  if (!value) return <div className="aster-bot-status unreliable"><header><span>BOTSTATUS</span><strong>STATUS NIET BETROUWBAAR</strong></header><p>Het volledige servercontract is nog niet bevestigd. Er wordt geen positieve bot- of instapstatus getoond.</p><div className="bot-entry-status unknown"><strong>INSTAPSTATUS ONBEKEND</strong><span>Wacht op actuele, bewezen servergegevens.</span></div></div>;
  const entryTone = value.newEntry.status.toLowerCase();
  return <div className={`aster-bot-status ${value.dataFresh ? "" : "unreliable"}`}>
    <header><span>BOTSTATUS</span><small>{value.dataFresh ? `Bijgewerkt ${time(value.evaluatedAt)}` : "STATUS NIET BETROUWBAAR"}</small></header>
    <div className="bot-strategies">
      {([3, 2] as const).map((id) => { const strategy = id === 3 ? value.strategy3 : value.strategy2; return <button key={id} type="button" className={`bot-strategy ${strategy.status.toLowerCase()}`} aria-expanded={open === id} onClick={() => setOpen(open === id ? null : id)}><span>STRATEGY {id}</span><strong>{runtimeLabel[strategy.status] || "ONBEKEND"}</strong><em>{strategy.status === "LIVE" ? "LIVE" : strategy.mode}</em><small>{strategy.ownedPositions} posities beheerd</small><i>{open === id ? "−" : "+"}</i></button>; })}
    </div>
    {open && <StrategyDetail id={open} value={open === 3 ? value.strategy3 : value.strategy2} />}
    <div className="bot-account-line"><div><span>ACCOUNTPOSITIES</span><strong>{value.account.activePositions} / {value.strategy3.maximumPositions}</strong></div><div><span>DOOR STRATEGY 3 BEHEERD</span><strong>{value.strategy3.ownedPositions}</strong></div><div><span>RESTERENDE RUIMTE</span><strong>{value.strategy3.remainingAccountCapacity}</strong></div></div>
    <p className="bot-direction-line"><b>{value.account.longPositions} LONG</b><i /> <b>{value.account.shortPositions} SHORT</b><span>{value.account.openOrders} open orders</span></p>
    <div className={`bot-entry-status ${entryTone}`}><strong>{entryLabel[value.newEntry.status]}</strong><span>{value.newEntry.reasonText}</span></div>
    <div className="bot-last-proof"><span>Laatste controle: <b>{time(value.strategy3.lastTickAt)}</b></span><span>Laatste actie: <b>{value.strategy3.lastAction === "NIET_BEWEZEN" ? "Niet bewezen" : value.strategy3.lastAction}</b></span></div>
    {open === 3 && <details className="bot-checks"><summary>Alle instapcontroles ({value.newEntry.activeBlocks.length} aandachtspunten)</summary>{value.newEntry.checks.map((check) => <div className={check.status.toLowerCase()} key={check.code}><i>{check.status === "PASS" ? "✓" : check.status === "WAIT" ? "•" : "!"}</i><span>{check.text}</span></div>)}</details>}
  </div>;
}
