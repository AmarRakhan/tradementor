"use client";

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { authenticatedRequest } from "@/lib/cloud-client";

type EmergencyState = {
  enabled?: boolean;
  armed?: boolean;
  status?: "OFF" | "ARMED" | "EXECUTING" | "LOCKED" | string;
  startPortfolioValue?: number;
  triggerPortfolioValue?: number;
  triggerPercentage?: number;
  maxAllowedLoss?: number;
  currentPortfolioValue?: number | null;
  activatedAt?: string | null;
  triggeredAt?: string | null;
  lockedAt?: string | null;
  lastError?: string;
};

const REFERENCE = "file_00000000ca148210b52f9a8befc68d22";
const API = "/api/exchanges/aster/portfolio-emergency-hedge";
const money = (value: unknown) => `US$${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value) || 0)}`;
const pct = (value: unknown) => `${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(Number(value) || 0)}%`;
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

function ShieldIcon({ locked = false }: { locked?: boolean }) {
  return <span className="pnh-shield" aria-hidden="true"><svg viewBox="0 0 32 36"><path d="M16 2 28 7v9c0 8-4.9 14.1-12 18C8.9 30.1 4 24 4 16V7l12-5Z"/><path d={locked ? "M11 17h10v8H11zM13 17v-2a3 3 0 0 1 6 0v2" : "m10.5 18 3.5 3.5 7.5-8"}/></svg></span>;
}

export function AsterPortfolioEmergencyHedge() {
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<EmergencyState>({ status: "OFF" });
  const [draftEnabled, setDraftEnabled] = useState(false);
  const [draftStart, setDraftStart] = useState(0);
  const [draftTrigger, setDraftTrigger] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let frame = 0;
    let alive = true;
    const mount = () => {
      if (!alive) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const snapshot = document.querySelector<HTMLElement>(".aster-portfolio-snapshot");
        if (!snapshot) { setHost(null); return; }
        let node = document.getElementById("portfolio-noodhedge-host");
        if (!node) { node = document.createElement("div"); node.id = "portfolio-noodhedge-host"; }
        if (node.parentElement !== snapshot.parentElement || node.previousElementSibling !== snapshot) {
          snapshot.insertAdjacentElement("afterend", node);
        }
        setHost(node);
      });
    };
    const observer = new MutationObserver(mount);
    observer.observe(document.body, { childList: true, subtree: true });
    mount();
    return () => { alive = false; observer.disconnect(); cancelAnimationFrame(frame); document.getElementById("portfolio-noodhedge-host")?.remove(); };
  }, []);

  const refresh = useCallback(async (opening = false) => {
    try {
      const next = await authenticatedRequest(API, { cache: "no-store" }) as EmergencyState;
      setState(next);
      const activeSaved = next.enabled === true && ["ARMED", "EXECUTING", "LOCKED"].includes(String(next.status));
      if (!dirty || opening) {
        setDraftEnabled(next.enabled === true);
        if (activeSaved) {
          setDraftStart(Number(next.startPortfolioValue) || 0);
          setDraftTrigger(Number(next.triggerPortfolioValue) || 0);
        } else {
          const current = Number(next.currentPortfolioValue) || 0;
          setDraftStart(current);
          const storedTrigger = Number(next.triggerPortfolioValue) || 0;
          setDraftTrigger(storedTrigger > 0 && storedTrigger < current ? storedTrigger : current * 0.333);
        }
        setDirty(false);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Portfolio Noodhedge kon niet worden geladen.");
    }
  }, [dirty]);

  useEffect(() => {
    const first = window.setTimeout(() => { void refresh(false); }, 0);
    const timer = window.setInterval(() => { void refresh(false); }, 5000);
    return () => { window.clearTimeout(first); window.clearInterval(timer); };
  }, [refresh]);

  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => { void refresh(false); }, 0);
    return () => window.clearTimeout(timer);
  }, [open, refresh]); // explicit open may propose current value only when no active saved config

  const triggerPercentage = draftStart > 0 ? draftTrigger / draftStart * 100 : 0;
  const maxLoss = Math.max(0, draftStart - draftTrigger);
  const status = String(state.status || "OFF").toUpperCase();
  const locked = status === "LOCKED";
  const executing = status === "EXECUTING";
  const armed = status === "ARMED" && state.enabled === true;
  const compactStatus = locked ? "LOCKED" : executing ? "EXECUTING" : armed ? "Actief" : "Uit";

  const setTrigger = (value: number) => {
    if (!(draftStart > 0)) return;
    setDraftTrigger(clamp(value, 0.01, Math.max(0.01, draftStart - 0.01)));
    setDirty(true); setMessage("");
  };
  const sliderPercentage = clamp(triggerPercentage || 33.3, 10, 95);

  async function toggle(next: boolean) {
    if (locked || executing) return;
    if (next) {
      setDraftEnabled(true); setDirty(true); setMessage("Controleer de trigger en druk daarna op Opslaan & activeren.");
      return;
    }
    if (!state.enabled) { setDraftEnabled(false); setDirty(false); return; }
    setBusy(true); setMessage("Beveiliging uitschakelen…");
    try {
      const start = Number(state.startPortfolioValue) || Math.max(1, draftStart);
      const trigger = Number(state.triggerPortfolioValue) || Math.max(.01, Math.min(start - .01, draftTrigger));
      const nextState = await authenticatedRequest(API, { method: "PUT", body: JSON.stringify({ enabled: false, start_portfolio_value: start, trigger_portfolio_value: trigger }) }) as EmergencyState;
      setState(nextState); setDraftEnabled(false); setDirty(false); setMessage("Portfolio Noodhedge staat uit. Bestaande trading werkt ongewijzigd.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Uitschakelen is niet gelukt."); }
    finally { setBusy(false); }
  }

  async function save() {
    if (!draftEnabled || busy) return;
    if (!(draftStart > 0) || !(draftTrigger > 0) || draftTrigger >= draftStart) {
      setMessage("Kies een trigger boven US$0 en onder de startwaarde."); return;
    }
    setBusy(true); setMessage("Opslaan & activeren…");
    try {
      // Baseline is deliberately captured only on this explicit user action.
      const nextState = await authenticatedRequest(API, { method: "PUT", body: JSON.stringify({ enabled: true, start_portfolio_value: draftStart, trigger_portfolio_value: draftTrigger }) }) as EmergencyState;
      setState(nextState); setDraftEnabled(true); setDirty(false); setMessage("ARMED · Portfolio Noodhedge bewaakt de opgeslagen trigger server-side.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Activeren is niet gelukt."); }
    finally { setBusy(false); }
  }

  async function unlock() {
    if (!locked || busy) return;
    if (!window.confirm("Portfolio LOCKED beëindigen? Automatische trading mag daarna pas weer volgens de normale instellingen werken.")) return;
    setBusy(true);
    try {
      const nextState = await authenticatedRequest(`${API}/unlock`, { method: "POST", body: JSON.stringify({ confirm: true }) }) as EmergencyState;
      setState(nextState); setDraftEnabled(false); setDirty(false); setMessage("Portfolio Lock handmatig beëindigd.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Ontgrendelen is niet gelukt."); }
    finally { setBusy(false); }
  }

  const summaryTrigger = armed || executing || locked ? Number(state.triggerPortfolioValue) : draftTrigger;
  const summaryLoss = armed || executing || locked ? Number(state.maxAllowedLoss) : maxLoss;
  const current = Number(state.currentPortfolioValue) || 0;

  const ui = <section className={`pnh-shell ${open ? "is-open" : ""} ${locked ? "is-locked" : ""}`} data-reference={REFERENCE} data-status={status}>
    <button type="button" className="pnh-compact" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
      <ShieldIcon locked={locked}/><span className="pnh-compact-copy"><strong>PORTFOLIO NOODHEDGE</strong><small>{locked ? "🔒 PORTFOLIO LOCKED" : executing ? "Noodprocedure wordt uitgevoerd" : armed ? `Trigger ${money(state.triggerPortfolioValue)}` : "Uit"}</small></span><span className={`pnh-chip pnh-${status.toLowerCase()}`}>{compactStatus}</span><span className="pnh-chevron">⌄</span>
    </button>
    {open ? <div className="pnh-panel">
      <div className="pnh-title-row"><div><span className="pnh-kicker">VEILIGHEID · ASTER</span><h3><ShieldIcon locked={locked}/> PORTFOLIO NOODHEDGE</h3><p>Leg je volledige open futures-portfolio 1:1 vast zodra de opgeslagen portfoliowaarde wordt geraakt.</p></div><label className={`pnh-toggle ${draftEnabled ? "on" : ""} ${(locked || executing || busy) ? "disabled" : ""}`}><input type="checkbox" checked={draftEnabled} disabled={locked || executing || busy} onChange={(event) => void toggle(event.target.checked)}/><span><i/></span><b>{draftEnabled ? "AAN" : "UIT"}</b></label></div>

      {locked ? <div className="pnh-locked-banner"><ShieldIcon locked/><div><small>NOODHEDGE UITGEVOERD</small><strong>🔒 PORTFOLIO LOCKED</strong><p>Normale automatische trading blijft gepauzeerd. Beheer long/short-posities handmatig en beëindig de lock alleen bewust.</p></div></div> : null}
      {executing ? <div className="pnh-executing"><span className="pnh-spinner"/><div><small>EXECUTING</small><strong>Open posities worden 1:1 afgedekt</strong><p>Orders worden gereconcilieerd op werkelijk bevestigde Aster-fills. Geen blind retries.</p></div></div> : null}

      <div className={`pnh-config ${(draftEnabled && !locked && !executing) ? "enabled" : "muted"}`}>
        <article className="pnh-value-card"><div><small>STARTWAARDE</small><strong>{money(draftStart)}</strong></div><span>automatisch opgehaald</span></article>
        <div className="pnh-trigger-head"><div><small>ALLES HEDGEN ALS NOG OVER IS</small><strong>{money(draftTrigger)}</strong></div><b>{pct(triggerPercentage)}</b></div>
        <div className="pnh-slider-wrap"><input aria-label="Noodhedge trigger percentage" type="range" min="10" max="95" step="0.1" value={sliderPercentage} disabled={!draftEnabled || locked || executing} onChange={(event) => setTrigger(draftStart * Number(event.target.value) / 100)}/><div className="pnh-slider-labels"><span>10% resterend</span><span>95% resterend</span></div></div>
        <label className="pnh-manual"><span>Trigger handmatig</span><div><i>US$</i><input inputMode="decimal" type="number" min="0.01" max={Math.max(.01, draftStart - .01)} step="0.01" value={Number.isFinite(draftTrigger) ? draftTrigger.toFixed(2) : ""} disabled={!draftEnabled || locked || executing} onChange={(event) => setTrigger(Number(event.target.value))}/></div></label>
        <article className="pnh-loss"><small>MAX TOEGESTAAN VERLIES VANAF NU</small><strong>{money(maxLoss)}</strong><p>{pct(100 - triggerPercentage)} onder de gekozen startwaarde</p></article>
      </div>

      <div className="pnh-actions"><article><span>Ⅱ</span><div><strong>Pauzeert trading</strong><small>Geen seats, DCA, Smart Rescue, Profit Lock of auto-restart</small></div></article><article><span>×</span><div><strong>Annuleert orders</strong><small>Verstorende open orders worden eerst afgehandeld</small></div></article><article><span>≍</span><div><strong>Hedge open posities 1:1</strong><small>Per munt alleen de netto ontbrekende LONG/SHORT</small></div></article></div>
      <p className="pnh-sticky-note">Na activatie blijft de hedge actief tot jij handmatig ingrijpt.</p>

      <section className="pnh-summary"><header><span>SAMENVATTING</span><b><i/> LIVE</b></header><div><article><small>Huidige portfoliowaarde</small><strong>{money(current)}</strong></article><article><small>Noodhedge trigger</small><strong>{money(summaryTrigger)}</strong></article><article><small>Beschermd verlies</small><strong>{money(summaryLoss)}</strong></article></div></section>
      {state.lastError ? <div className="pnh-error">⚠ {state.lastError}</div> : null}
      {message ? <div className="pnh-message">{message}</div> : null}
      {locked ? <button type="button" className="pnh-unlock" disabled={busy} onClick={() => void unlock()}>Portfolio Lock handmatig beëindigen</button> : <button type="button" className="pnh-save" disabled={!draftEnabled || busy || executing || (!dirty && armed)} onClick={() => void save()}>{busy ? "Bezig…" : armed && !dirty ? "Actief · opgeslagen" : "Opslaan & activeren"}</button>}
    </div> : null}
    <style>{styles}</style>
  </section>;
  return host ? createPortal(ui, host) : null;
}

const styles = `
#portfolio-noodhedge-host{display:block;width:100%;margin:10px 0 12px}.pnh-shell{--green:#2cf2a2;--green2:#0edb87;--gold:#d8ad54;--ink:#04100b;--card:#06150f;position:relative;width:100%;overflow:hidden;border:1px solid rgba(72,230,168,.22);border-radius:17px;background:linear-gradient(145deg,rgba(4,17,11,.97),rgba(2,10,8,.99));box-shadow:0 14px 40px rgba(0,0,0,.28),inset 0 1px rgba(255,255,255,.025);color:#eef9f4;font-family:var(--font-geist-sans),sans-serif}.pnh-shell.is-open{border-color:rgba(57,238,167,.42);box-shadow:0 0 0 1px rgba(14,167,104,.08),0 18px 50px rgba(0,0,0,.38),0 0 24px rgba(21,220,145,.06)}.pnh-compact{appearance:none;width:100%;min-height:66px;border:0;background:linear-gradient(90deg,rgba(7,41,27,.62),rgba(5,16,12,.9));display:grid;grid-template-columns:38px 1fr auto 18px;align-items:center;gap:9px;padding:9px 13px;color:inherit;text-align:left}.pnh-shield{display:inline-grid;place-items:center;width:34px;height:34px}.pnh-shield svg{width:30px;height:33px;overflow:visible}.pnh-shield svg path:first-child{fill:rgba(24,225,147,.07);stroke:var(--green);stroke-width:2}.pnh-shield svg path:last-child{fill:none;stroke:var(--green);stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round}.pnh-compact-copy{display:grid;gap:3px;min-width:0}.pnh-compact-copy strong{font-size:12px;letter-spacing:.075em;color:#eef8f3}.pnh-compact-copy small{font-size:9px;color:#7f9a8d;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.pnh-chip{padding:5px 8px;border:1px solid rgba(121,148,135,.2);border-radius:999px;color:#819a8f;font-size:8px;font-weight:900;letter-spacing:.06em}.pnh-chip.pnh-armed{border-color:rgba(44,242,162,.34);color:#50efb0;background:rgba(21,157,101,.11)}.pnh-chip.pnh-executing{border-color:rgba(216,173,84,.5);color:#e8c46f;background:rgba(140,100,22,.14)}.pnh-chip.pnh-locked{border-color:rgba(44,242,162,.58);color:#b5ffdd;background:rgba(24,205,131,.15);box-shadow:0 0 12px rgba(44,242,162,.08)}.pnh-chevron{color:#70a18a;font-size:16px;transform:rotate(0);transition:.2s}.pnh-shell.is-open .pnh-chevron{transform:rotate(180deg)}.pnh-panel{padding:14px 14px 16px;border-top:1px solid rgba(44,242,162,.11);background:radial-gradient(circle at 85% 0,rgba(20,130,84,.12),transparent 32%),linear-gradient(180deg,rgba(3,16,11,.98),rgba(2,9,7,.99))}.pnh-title-row{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.pnh-kicker{display:block;margin-bottom:3px;color:var(--gold);font-size:7px;font-weight:800;letter-spacing:.17em}.pnh-title-row h3{display:flex;align-items:center;gap:5px;margin:0;color:#f1d189;font-size:16px;letter-spacing:.04em}.pnh-title-row h3 .pnh-shield{width:25px;height:27px}.pnh-title-row h3 .pnh-shield svg{width:23px;height:26px}.pnh-title-row p{max-width:430px;margin:5px 0 0;color:#739083;font-size:8.5px;line-height:1.45}.pnh-toggle{display:grid;justify-items:center;gap:3px;flex:0 0 auto}.pnh-toggle input{position:absolute;opacity:0;pointer-events:none}.pnh-toggle>span{position:relative;width:42px;height:23px;border:1px solid rgba(100,122,112,.35);border-radius:99px;background:#0b1511;box-shadow:inset 0 2px 7px rgba(0,0,0,.45)}.pnh-toggle>span i{position:absolute;left:3px;top:3px;width:15px;height:15px;border-radius:50%;background:#708078;transition:.18s}.pnh-toggle.on>span{border-color:rgba(44,242,162,.65);background:linear-gradient(90deg,#096c48,#0dac70);box-shadow:0 0 12px rgba(44,242,162,.13)}.pnh-toggle.on>span i{left:22px;background:#d7ffeb;box-shadow:0 0 8px rgba(255,255,255,.4)}.pnh-toggle b{font-size:7px;color:#789084}.pnh-toggle.on b{color:#4cf1af}.pnh-toggle.disabled{opacity:.55}.pnh-locked-banner,.pnh-executing{display:grid;grid-template-columns:46px 1fr;gap:10px;align-items:center;margin:13px 0 0;padding:11px;border:1px solid rgba(44,242,162,.4);border-radius:13px;background:linear-gradient(100deg,rgba(7,70,45,.48),rgba(4,25,17,.64));box-shadow:inset 0 0 20px rgba(44,242,162,.035)}.pnh-locked-banner>.pnh-shield{width:43px;height:43px}.pnh-locked-banner small,.pnh-executing small{color:#4cf1af;font-size:7px;letter-spacing:.14em}.pnh-locked-banner strong,.pnh-executing strong{display:block;margin-top:2px;color:#dffbed;font-size:14px}.pnh-locked-banner p,.pnh-executing p{margin:3px 0 0;color:#7f9b8e;font-size:8px;line-height:1.4}.pnh-executing{border-color:rgba(216,173,84,.36);background:rgba(53,37,8,.22)}.pnh-executing small{color:#e4b952}.pnh-spinner{width:28px;height:28px;border:2px solid rgba(216,173,84,.2);border-top-color:#e3b553;border-radius:50%;animation:pnhspin .85s linear infinite;margin:auto}@keyframes pnhspin{to{transform:rotate(360deg)}}.pnh-config{margin-top:12px;transition:.2s}.pnh-config.muted{opacity:.46;filter:saturate(.65)}.pnh-value-card{display:flex;align-items:center;justify-content:space-between;padding:11px 12px;border:1px solid rgba(216,173,84,.18);border-radius:12px;background:linear-gradient(120deg,rgba(35,28,10,.36),rgba(6,22,15,.55))}.pnh-value-card small,.pnh-trigger-head small,.pnh-loss small{display:block;color:#9e895a;font-size:7px;font-weight:900;letter-spacing:.11em}.pnh-value-card strong{display:block;margin-top:3px;font-size:21px;color:#f6f8f3}.pnh-value-card>span{color:#779185;font-size:7.5px}.pnh-trigger-head{display:flex;align-items:flex-end;justify-content:space-between;margin:15px 2px 7px}.pnh-trigger-head strong{display:block;margin-top:2px;font-size:24px;color:#fff}.pnh-trigger-head>b{padding:6px 9px;border:1px solid rgba(44,242,162,.34);border-radius:9px;background:rgba(18,150,96,.1);color:#4ef0b0;font-size:13px}.pnh-slider-wrap{padding:5px 3px 2px}.pnh-slider-wrap input{appearance:none;width:100%;height:8px;border-radius:999px;outline:0;background:linear-gradient(90deg,#17d78c 0%,#38f0ab var(--pnh-p,70%),rgba(42,79,62,.65) var(--pnh-p,70%));accent-color:#32eca7}.pnh-slider-wrap input::-webkit-slider-thumb{appearance:none;width:22px;height:22px;border:3px solid #09271b;border-radius:50%;background:#51f3b6;box-shadow:0 0 0 2px rgba(59,239,174,.28),0 0 14px rgba(45,236,166,.25)}.pnh-slider-labels{display:flex;justify-content:space-between;margin-top:7px;color:#637d71;font-size:7px}.pnh-manual{display:flex;align-items:center;justify-content:space-between;gap:9px;margin-top:11px;padding:8px 9px;border:1px solid rgba(53,119,89,.2);border-radius:10px;background:rgba(4,21,14,.6)}.pnh-manual>span{font-size:8px;color:#8ba195}.pnh-manual>div{display:flex;align-items:center;border:1px solid rgba(42,211,146,.25);border-radius:8px;background:#04100b;overflow:hidden}.pnh-manual i{padding:0 0 0 8px;color:#4edfa7;font-size:8px;font-style:normal}.pnh-manual input{width:92px;min-height:30px;border:0;outline:0;background:transparent;color:#eaf9f1;font-size:12px;font-weight:800;text-align:right;padding:0 8px}.pnh-loss{margin-top:10px;padding:12px;border:1px solid rgba(44,242,162,.26);border-radius:12px;background:linear-gradient(120deg,rgba(7,49,33,.55),rgba(5,24,17,.62));text-align:center}.pnh-loss small{color:#52dca6}.pnh-loss strong{display:block;margin-top:3px;color:#5cf1b6;font-size:24px;text-shadow:0 0 15px rgba(44,242,162,.12)}.pnh-loss p{margin:2px 0 0;color:#728d80;font-size:7px}.pnh-actions{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:12px}.pnh-actions article{min-height:82px;padding:9px 8px;border:1px solid rgba(61,131,99,.18);border-radius:11px;background:rgba(5,21,15,.72);text-align:center}.pnh-actions article>span{display:grid;place-items:center;width:25px;height:25px;margin:0 auto 6px;border:1px solid rgba(44,242,162,.28);border-radius:8px;color:#48efae;font-size:14px}.pnh-actions strong{display:block;color:#cfdfd6;font-size:8px}.pnh-actions small{display:block;margin-top:3px;color:#62796e;font-size:6.5px;line-height:1.35}.pnh-sticky-note{margin:8px 0 0;color:#819a8e;font-size:7.5px;text-align:center}.pnh-summary{margin-top:12px;border:1px solid rgba(216,173,84,.19);border-radius:12px;background:linear-gradient(120deg,rgba(31,25,10,.26),rgba(4,19,13,.54));overflow:hidden}.pnh-summary header{display:flex;justify-content:space-between;align-items:center;padding:8px 10px;border-bottom:1px solid rgba(216,173,84,.12)}.pnh-summary header>span{color:#b79c62;font-size:7px;font-weight:900;letter-spacing:.13em}.pnh-summary header b{display:flex;align-items:center;gap:4px;color:#4ff0b0;font-size:7px}.pnh-summary header i{width:6px;height:6px;border-radius:50%;background:#38efa9;box-shadow:0 0 8px #38efa9}.pnh-summary>div{display:grid;grid-template-columns:repeat(3,1fr)}.pnh-summary article{padding:9px 7px;text-align:center;border-right:1px solid rgba(216,173,84,.1)}.pnh-summary article:last-child{border-right:0}.pnh-summary small{display:block;color:#71897e;font-size:6.5px}.pnh-summary strong{display:block;margin-top:3px;color:#e9f3ee;font-size:11px}.pnh-summary article:nth-child(2) strong{color:#e4bd65}.pnh-summary article:nth-child(3) strong{color:#51eeb0}.pnh-error,.pnh-message{margin-top:8px;padding:8px 9px;border-radius:9px;font-size:7.5px;line-height:1.4}.pnh-error{border:1px solid rgba(247,118,126,.25);background:rgba(93,20,27,.25);color:#f09299}.pnh-message{border:1px solid rgba(89,161,128,.2);background:rgba(7,33,22,.55);color:#91ad9f}.pnh-save,.pnh-unlock{width:100%;min-height:47px;margin-top:11px;border-radius:12px;font-size:11px;font-weight:950;letter-spacing:.04em}.pnh-save{border:1px solid #38e9a5;background:linear-gradient(180deg,#17c77f,#0a8859);color:#02150d;box-shadow:0 0 18px rgba(44,242,162,.14),inset 0 1px rgba(255,255,255,.28)}.pnh-save:disabled{opacity:.42;box-shadow:none}.pnh-unlock{border:1px solid rgba(216,173,84,.45);background:rgba(102,72,18,.2);color:#e3bf6b}.pnh-shell.is-locked{border-color:rgba(44,242,162,.5)}@media(max-width:430px){#portfolio-noodhedge-host{margin:8px 0 10px}.pnh-shell{border-radius:15px}.pnh-compact{min-height:62px;grid-template-columns:34px 1fr auto 13px;padding:8px 10px;gap:7px}.pnh-compact-copy strong{font-size:10px}.pnh-compact-copy small{font-size:7.5px}.pnh-chip{font-size:7px;padding:4px 6px}.pnh-panel{padding:12px 10px 13px}.pnh-title-row h3{font-size:13px}.pnh-title-row p{font-size:7.5px}.pnh-value-card strong{font-size:18px}.pnh-trigger-head strong{font-size:21px}.pnh-actions{grid-template-columns:1fr}.pnh-actions article{display:grid;grid-template-columns:30px 1fr;align-items:center;gap:7px;min-height:50px;text-align:left}.pnh-actions article>span{margin:0}.pnh-summary>div{grid-template-columns:1fr}.pnh-summary article{display:flex;justify-content:space-between;align-items:center;border-right:0;border-bottom:1px solid rgba(216,173,84,.08);text-align:left}.pnh-summary article:last-child{border-bottom:0}.pnh-summary strong{font-size:10px}.pnh-manual input{width:84px}}`;
