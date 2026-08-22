"use client";

import { useState } from "react";
import { parseAsterBotStatus, type StrategyDashboardStatus } from "@/lib/aster-bot-status";

const runtimeLabel: Record<string, string> = {
  LIVE: "ACTIEF",
  PAPER: "PAPER",
  STOPPED: "UIT",
  BLOCKED: "GEBLOKKEERD",
  RECOVERING: "HERSTEL",
  UNKNOWN: "ONBEKEND",
};

const entryLabel: Record<string, string> = {
  ALLOWED: "AANVULLEN ACTIEF",
  WAITING: "AANVULLEN WACHT",
  BLOCKED: "AANVULLEN GEBLOKKEERD",
  UNKNOWN: "INSTAPSTATUS ONBEKEND",
};

function time(value: unknown) {
  const date = new Date(String(value || ""));
  return Number.isFinite(date.getTime())
    ? date.toLocaleString("nl-NL", { dateStyle: "short", timeStyle: "medium" })
    : "Niet bewezen";
}

function StrategyDetail({ value }: { value: StrategyDashboardStatus }) {
  return (
    <section className="bot-strategy-detail" aria-label="Strategy 2 details">
      <dl>
        <div><dt>Modus</dt><dd>{value.mode}</dd></div>
        <div><dt>Fase</dt><dd>{value.phase}</dd></div>
        <div><dt>Scheduler</dt><dd>{value.schedulerStatus.status}</dd></div>
        <div><dt>Eigen posities</dt><dd>{value.ownedPositions}</dd></div>
        <div><dt>Laatste controle</dt><dd>{time(value.lastTickAt)}</dd></div>
      </dl>
      <p><b>Laatste bewezen actie</b>{value.lastAction === "NIET_BEWEZEN" ? "Niet bewezen" : value.lastAction}</p>
      <p><b>Laatste reden</b>{value.lastReason}</p>
    </section>
  );
}

export function AsterBotStatus({ snapshot }: { snapshot: Record<string, unknown> | null }) {
  const [open, setOpen] = useState(false);
  const [strategyOpen, setStrategyOpen] = useState(false);
  const value = parseAsterBotStatus(snapshot);

  if (!value) {
    return (
      <>
        <style>{asterCompactStyles}</style>
        <div className="aster-bot-status compact-shell unreliable">
          <button type="button" className="bot-status-summary" disabled>
            <span>BOTSTATUS · STRATEGY 2</span>
            <strong>STATUS NIET BETROUWBAAR</strong>
          </button>
        </div>
      </>
    );
  }

  const entryTone = value.newEntry.status.toLowerCase();
  const statusText = runtimeLabel[value.strategy2.status] || "ONBEKEND";

  return (
    <>
      <style>{asterCompactStyles}</style>
      <div className={`aster-bot-status compact-shell ${value.dataFresh ? "" : "unreliable"}`}>
        <button
          type="button"
          className={`bot-status-summary ${value.strategy2.status.toLowerCase()}`}
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
        >
          <span className="summary-label">STRATEGY 2</span>
          <strong>{statusText}</strong>
          <span className="summary-count">{value.strategy2.ownedPositions}/{value.targetPositions} posities</span>
          <span className="summary-direction">{value.account.longPositions}L · {value.account.shortPositions}S</span>
          <i aria-hidden="true">{open ? "▴" : "▾"}</i>
        </button>

        {open && (
          <div className="bot-status-expanded">
            <header>
              <span>BOTSTATUS · ALLEEN STRATEGY 2</span>
              <small>{value.dataFresh ? `Bijgewerkt ${time(value.evaluatedAt)}` : "STATUS NIET BETROUWBAAR"}</small>
            </header>

            <div className="bot-strategies">
              <button
                type="button"
                className={`bot-strategy ${value.strategy2.status.toLowerCase()}`}
                aria-expanded={strategyOpen}
                onClick={() => setStrategyOpen((current) => !current)}
              >
                <span>STRATEGY 2</span>
                <strong>{statusText}</strong>
                <em>{value.strategy2.status === "LIVE" ? "LIVE" : value.strategy2.mode}</em>
                <small>{value.strategy2.ownedPositions} posities beheerd</small>
                <i>{strategyOpen ? "−" : "+"}</i>
              </button>
            </div>

            {strategyOpen && <StrategyDetail value={value.strategy2} />}

            <div className="bot-account-line">
              <div><span>ACCOUNTPOSITIES</span><strong>{value.account.activePositions}</strong></div>
              <div><span>STRATEGY 2 · BEHEERD / DOEL</span><strong>{value.strategy2.ownedPositions} / {value.targetPositions}</strong></div>
              <div><span>NOG TE VULLEN</span><strong>{value.remainingToTarget}</strong></div>
            </div>

            <p className="bot-direction-line">
              <b>{value.account.longPositions} LONG</b><i/><b>{value.account.shortPositions} SHORT</b>
              <span>{value.account.openOrders} open orders</span>
            </p>

            <div className={`bot-entry-status ${entryTone}`}>
              <strong>{entryLabel[value.newEntry.status]}</strong>
              <span>{value.newEntry.reasonText}</span>
            </div>

            <div className="bot-last-proof">
              <span>Laatste Strategy-2-controle: <b>{time(value.strategy2.lastTickAt)}</b></span>
              <span>Laatste Strategy-2-actie: <b>{value.strategy2.lastAction === "NIET_BEWEZEN" ? "Niet bewezen" : value.strategy2.lastAction}</b></span>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

const asterCompactStyles = `
  .mobile-context { display: none !important; }
  .hero-panel:has(.aster-bot-status.compact-shell) {
    min-height: 0 !important;
    display: block !important;
    padding: 10px 12px !important;
    border-radius: 16px !important;
  }
  .hero-panel:has(.aster-bot-status.compact-shell)::after { display: none !important; }
  .aster-bot-status.compact-shell { display: block; width: 100%; }
  .bot-status-summary {
    width: 100%; min-height: 42px; display: grid;
    grid-template-columns: auto auto 1fr auto auto; align-items: center;
    gap: 8px; padding: 7px 9px; border: 1px solid rgba(114,141,179,.16);
    border-radius: 11px; background: rgba(6,16,29,.56); text-align: left; cursor: pointer;
  }
  .bot-status-summary.live { border-color: rgba(69,224,164,.28); background: linear-gradient(135deg,rgba(25,120,84,.13),rgba(6,21,30,.58)); }
  .bot-status-summary .summary-label { color: #8ea0b7; font-size: 8px; font-weight: 900; letter-spacing: .10em; }
  .bot-status-summary strong { color: #c9d5e5; font-size: 11px; line-height: 1; }
  .bot-status-summary.live strong { color: #76edbe; }
  .bot-status-summary .summary-count, .bot-status-summary .summary-direction { color: #8b9bb0; font-size: 9px; white-space: nowrap; }
  .bot-status-summary .summary-count { text-align: right; }
  .bot-status-summary i { color: #7e91aa; font-size: 12px; font-style: normal; }
  .bot-status-expanded { display: grid; gap: 9px; padding-top: 10px; }
  .bot-status-expanded > header { display: flex; justify-content: space-between; gap: 10px; align-items: center; }
  .bot-status-expanded > header > span { color: #71d8b1; font-size: 8px; font-weight: 900; letter-spacing: .12em; }
  .bot-status-expanded > header > small { color: #72839a; font-size: 7px; }
  .bot-status-expanded .bot-strategies { grid-template-columns: 1fr; }
  .bot-status-expanded .bot-strategy { padding-top: 9px; padding-bottom: 9px; }
  @media (max-width: 600px) {
    .content { padding-top: 10px !important; }
    .hero-panel:has(.aster-bot-status.compact-shell) { padding: 8px !important; }
    .bot-status-summary { min-height: 40px; grid-template-columns: auto auto 1fr auto; gap: 6px; }
    .bot-status-summary .summary-label { font-size: 7px; }
    .bot-status-summary strong { font-size: 10px; }
    .bot-status-summary .summary-count { font-size: 8px; }
    .bot-status-summary .summary-direction { display: none; }
  }
`;
