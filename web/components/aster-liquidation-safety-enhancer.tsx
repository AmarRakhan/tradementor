"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { authenticatedRequest } from "@/lib/cloud-client";

type SafetyStatus = "VEILIG" | "OPLETTEN" | "HOOG_RISICO" | "KRITIEK" | "DATA_ONBETROUWBAAR";
type DynamicState = {
  reliable?: boolean; monitoringAlwaysActive?: boolean; enabled?: boolean; ownershipState?: string;
  engineState?: string; reasonCode?: string; safetyStatus?: SafetyStatus; adoptedPositionCount?: number;
  positionCount?: number; longPositionCount?: number; shortPositionCount?: number; longExposureUsd?: number;
  shortExposureUsd?: number; netExposureUsd?: number; netSide?: "LONG" | "SHORT" | "FLAT" | string;
  grossExposureUsd?: number; hedgeCoveragePercent?: number | null; equity?: number; marginBalance?: number;
  maintenanceMarginUsd?: number; marginBufferUsd?: number | null; bufferRatio?: number | null;
  liquidationRiskPct?: number | null; liquidationRiskSource?: string; targetMinPercent?: number | null;
  targetMaxPercent?: number | null; recommendedAction?: string; riskAddingAllowed?: boolean;
  executionGateOpen?: boolean; lastAction?: string; lastActionAt?: string | null; lastReason?: string;
  capturedAt?: string | null; generatedAt?: string | null;
};

function number(value: unknown): number | null { const parsed = Number(value); return Number.isFinite(parsed) ? parsed : null; }
function money(value: unknown, decimals = 2): string { const parsed = number(value); if (parsed === null) return "—"; return `US$ ${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(Math.abs(parsed))}`; }
function signedMoney(value: unknown): string { const parsed = number(value); if (parsed === null) return "—"; return `${parsed > 0 ? "+" : parsed < 0 ? "-" : ""}${money(parsed, 0)}`; }
function percent(value: unknown, decimals = 1): string { const parsed = number(value); if (parsed === null) return "—"; return `${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(parsed)}%`; }
function ratio(value: unknown): string { const parsed = number(value); if (parsed === null) return "—"; return `${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(parsed)}×`; }
function shortTime(value: string | null | undefined): string { if (!value) return "—"; const date = new Date(value); if (!Number.isFinite(date.getTime())) return "—"; return new Intl.DateTimeFormat("nl-NL", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date); }

function statusCopy(status: SafetyStatus) {
  if (status === "VEILIG") return { title: "Liquidatieveiligheid: VEILIG", detail: "Ruime bevestigde marginbuffer boven maintenance." };
  if (status === "OPLETTEN") return { title: "Liquidatieveiligheid: OPLETTEN", detail: "Marginruimte neemt af. Nieuwe exposure wordt extra streng beoordeeld." };
  if (status === "HOOG_RISICO") return { title: "Liquidatieveiligheid: HOOG RISICO", detail: "Marginbuffer is krap. Risk-adding acties horen beperkt te worden." };
  if (status === "KRITIEK") return { title: "Liquidatieveiligheid: KRITIEK", detail: "Liquidatiebuffer is kritiek. Extra exposure mag niet blind worden toegevoegd." };
  return { title: "Liquidatieveiligheid: DATA ONBETROUWBAAR", detail: "Actuele Aster margin-data is niet betrouwbaar genoeg voor een groene veiligheidsstatus." };
}

function engineCopy(state: DynamicState) {
  const engine = String(state.engineState || "MONITORING").toUpperCase();
  if (!state.enabled) return { title: "Monitoring actief", detail: "Automatische hedge UIT · geen automatische hedge-aanpassingen." };
  if (String(state.ownershipState).toUpperCase() === "ADOPTING" || engine === "POSITIONS_ADOPTING") return { title: "Posities overnemen", detail: `${state.adoptedPositionCount ?? state.positionCount ?? 0} bestaande posities worden gereconcilieerd.` };
  if (engine === "HEDGE_BUILDING") return { title: "Hedge opbouwen", detail: "Koersrisico wordt gecontroleerd richting de actuele doelzone bijgestuurd." };
  if (engine === "HEDGE_REDUCING") return { title: "Hedge afbouwen", detail: "Gross exposure wordt gecontroleerd verlaagd richting de actuele doelzone." };
  if (engine === "HEDGE_STABLE") return { title: "Hedge stabiel", detail: "Hedge ligt binnen de actuele doelzone." };
  if (engine === "PROTECT_MARGIN_BUFFER") return { title: "Marginbuffer beschermen", detail: "Extra hedge kan zijn geblokkeerd wanneer de marginstructuur daardoor onveiliger wordt." };
  if (engine === "REDUCE_GROSS_EXPOSURE") return { title: "Gross exposure verlagen", detail: "Liquidatiebuffer heeft prioriteit boven extra hedge." };
  if (engine === "DATA_UNRELIABLE") return { title: "Automatisering gepauzeerd", detail: "Geen risk-adding actie zolang Aster-data niet betrouwbaar is." };
  if (engine === "AUTOMATION_PAUSED") return { title: "Automatisering gepauzeerd", detail: state.executionGateOpen === false ? "Live Dynamic Hedge execution is centraal vergrendeld." : "Automatische hedge-acties zijn tijdelijk gepauzeerd." };
  return { title: "Realtime hedge-monitoring", detail: "Hedge, gross exposure en marginbuffer worden bewaakt." };
}

function actionCopy(action: string | undefined) {
  const value = String(action || "HOLD").toUpperCase();
  if (value === "OPEN_SHORT") return "SHORT hedge verhogen als projected margin veilig blijft";
  if (value === "OPEN_LONG") return "LONG hedge verhogen als projected margin veilig blijft";
  if (value === "CLOSE_SHORT") return "SHORT exposure gecontroleerd verminderen";
  if (value === "CLOSE_LONG") return "LONG exposure gecontroleerd verminderen";
  if (value === "REDUCE_GROSS_EXPOSURE") return "gross exposure verlagen; marginbuffer heeft prioriteit";
  return "geen risk-adding actie nodig";
}

function Metric({ label, value, sub, tone = "neutral" }: { label: string; value: string; sub?: string; tone?: string }) { return <div className={`als-metric als-${tone}`}><small>{label}</small><strong>{value}</strong>{sub ? <em>{sub}</em> : null}</div>; }
function findSnapshot(): HTMLElement | null { return document.querySelector<HTMLElement>(".aster-portfolio-snapshot"); }

export function AsterLiquidationSafetyEnhancer() {
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [state, setState] = useState<DynamicState | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [infoOpen, setInfoOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const value = await authenticatedRequest("/api/exchanges/aster/dynamic-hedge/state", { cache: "no-store" }) as DynamicState;
      setState(value); setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Liquidation Safety-data kon niet worden geladen.");
      setState((current) => current ? { ...current, reliable: false, safetyStatus: "DATA_ONBETROUWBAAR", engineState: "DATA_UNRELIABLE" } : null);
    }
  }, []);

  useEffect(() => {
    const mount = () => {
      const snapshot = findSnapshot(); if (!snapshot) return;
      let node = snapshot.querySelector<HTMLElement>("#aster-liquidation-safety-host");
      if (!node) { node = document.createElement("div"); node.id = "aster-liquidation-safety-host"; const grid = snapshot.querySelector(".aps-grid"); if (grid?.nextSibling) snapshot.insertBefore(node, grid.nextSibling); else snapshot.appendChild(node); }
      setHost(node);
    };
    mount(); const observer = new MutationObserver(mount); observer.observe(document.body, { childList: true, subtree: true }); return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!host) return; void load();
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") void load(); }, 30_000);
    const visible = () => { if (document.visibilityState === "visible") void load(); };
    document.addEventListener("visibilitychange", visible); window.addEventListener("tradementor:refresh", visible as EventListener);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", visible); window.removeEventListener("tradementor:refresh", visible as EventListener); };
  }, [host, load]);

  useEffect(() => {
    if (!host) return; const snapshot = host.closest(".aster-portfolio-snapshot");
    const cards = Array.from(snapshot?.querySelectorAll<HTMLElement>(".aps-metric") || []);
    const card = cards.find((item) => item.querySelector("small")?.textContent?.toUpperCase().includes("AVAILABLE TO TRADE"));
    if (!card || card.querySelector(".als-available-info-button")) return;
    const button = document.createElement("button"); button.type = "button"; button.className = "als-available-info-button"; button.setAttribute("aria-label", "Uitleg over Available to Trade"); button.title = "Available is geen liquidatiemeter"; button.textContent = "i";
    const onClick = (event: Event) => { event.preventDefault(); event.stopPropagation(); setInfoOpen(true); };
    button.addEventListener("click", onClick); card.appendChild(button); return () => { button.removeEventListener("click", onClick); button.remove(); };
  }, [host]);

  const stale = useMemo(() => { const value = state?.capturedAt || state?.generatedAt; if (!value) return true; const stamp = Date.parse(value); return !Number.isFinite(stamp) || Date.now() - stamp > 90_000; }, [state?.capturedAt, state?.generatedAt]);
  const safety = (!state || !state.reliable || stale ? "DATA_ONBETROUWBAAR" : (state.safetyStatus || "DATA_ONBETROUWBAAR")) as SafetyStatus;
  const copy = statusCopy(safety); const engine = engineCopy({ ...(state || {}), ...(stale ? { engineState: "DATA_UNRELIABLE" } : {}) });
  const coverage = number(state?.hedgeCoveragePercent); const targetMin = number(state?.targetMinPercent); const targetMax = number(state?.targetMaxPercent); const liquidation = number(state?.liquidationRiskPct);
  const bufferRemaining = liquidation === null ? null : Math.max(0, Math.min(100, 100 - liquidation)); const hedgeWidth = coverage === null ? 0 : Math.max(0, Math.min(100, coverage));

  const toggle = async () => {
    if (!state || busy) return; const next = !state.enabled;
    const question = next ? "Dynamische hedge inschakelen? Bestaande posities worden eerst alleen overgenomen en gereconcilieerd; er wordt door het inschakelen zelf niets gesloten of opnieuw geopend." : "Dynamische hedge uitschakelen? Automatisch hedgebeheer stopt, maar bestaande LONG- en SHORT-posities blijven open.";
    if (!window.confirm(question)) return; setBusy(true); setMessage("");
    try { const value = await authenticatedRequest("/api/exchanges/aster/dynamic-hedge/enabled", { method: "PUT", body: JSON.stringify({ enabled: next, confirm: true }) }) as DynamicState; setState(value); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Dynamic Hedge kon niet veilig worden gewijzigd."); }
    finally { setBusy(false); }
  };

  if (!host) return null;
  return createPortal(<>
    <section className={`als-panel als-status-${safety.toLowerCase().replaceAll("_", "-")}`} aria-label="Hedge en liquidatieveiligheid">
      <header className="als-header"><div className="als-title"><span className="als-shield">◇</span><div><b>HEDGE &amp; LIQUIDATION SAFETY</b><small>Directioneel risico en echte marginruimte apart bewaakt</small></div></div><div className="als-controls"><span className="als-monitor"><i />Monitoring: altijd actief</span><button type="button" role="switch" aria-checked={Boolean(state?.enabled)} className={`als-toggle ${state?.enabled ? "on" : "off"}`} disabled={!state || busy || (!state.enabled && safety === "DATA_ONBETROUWBAAR")} onClick={toggle}><span>Dynamische hedge: <b>{state?.enabled ? "AAN" : "UIT"}</b></span><i /></button></div></header>
      <div className="als-summary-row"><div className={`als-safety-card als-tone-${safety.toLowerCase().replaceAll("_", "-")}`}><span>◇</span><div><strong>{copy.title}</strong><small>{copy.detail}</small></div></div><button className="als-available-warning" type="button" onClick={() => setInfoOpen(true)}><b>!</b><span><strong>Available is geen liquidatiemeter.</strong><small>Liquidatierisico wordt bepaald door equity/margin balance versus maintenance margin.</small></span></button></div>
      <div className="als-metrics-grid"><Metric label="HEDGE DEKKING" value={percent(coverage)} sub={targetMin !== null && targetMax !== null ? `Doel ${percent(targetMin, 0)}–${percent(targetMax, 0)}` : "Doel tijdelijk geblokkeerd"} tone="hedge" /><Metric label="NETTO EXPOSURE" value={signedMoney(state?.netExposureUsd)} sub={String(state?.netSide || "—")} tone="net" /><Metric label="GROSS EXPOSURE" value={money(state?.grossExposureUsd, 0)} sub="LONG + SHORT" tone="gross" /><Metric label="BUFFER RATIO" value={ratio(state?.bufferRatio)} sub="Equity ÷ maintenance" tone="buffer" /><Metric label="EQUITY / MARGIN BALANCE" value={money(state?.marginBalance ?? state?.equity)} sub="Aster account basis" tone="equity" /><Metric label="MAINTENANCE MARGIN" value={money(state?.maintenanceMarginUsd)} sub="Aster minimum requirement" tone="maintenance" /><Metric label="MARGIN BUFFER" value={state?.marginBufferUsd === null || state?.marginBufferUsd === undefined ? "—" : signedMoney(state.marginBufferUsd)} sub="Equity − maintenance" tone="buffer" /><Metric label="LIQUIDATIERISICO" value={percent(liquidation, 2)} sub="100% = kritieke grens" tone="liquidation" /></div>
      <div className="als-bars"><div className="als-bar-card"><div className="als-bar-label"><b>Hedge Dekking</b><span>huidig vs. dynamisch doelbereik</span></div><div className="als-track als-hedge-track"><i style={{ width: `${hedgeWidth}%` }} />{targetMin !== null ? <b style={{ left: `${Math.max(0, Math.min(100, targetMin))}%` }} /> : null}{targetMax !== null ? <b style={{ left: `${Math.max(0, Math.min(100, targetMax))}%` }} /> : null}</div><div className="als-bar-values"><strong>{percent(coverage)}</strong><span>{targetMin !== null && targetMax !== null ? `Doelbereik ${percent(targetMin, 0)}–${percent(targetMax, 0)}` : "Geen risk-adding doel"}</span><em>100%</em></div></div><div className="als-bar-card"><div className="als-bar-label"><b>Liquidatie Buffer</b><span>equity vs. maintenance</span></div><div className="als-track als-liquid-track"><i style={{ width: `${bufferRemaining ?? 0}%` }} /></div><div className="als-buffer-values"><span><b>{money(state?.maintenanceMarginUsd)}</b><small>Maintenance</small></span><strong>Vrije veiligheidsruimte: {state?.marginBufferUsd === null || state?.marginBufferUsd === undefined ? "—" : signedMoney(state.marginBufferUsd)}</strong><span><b>{money(state?.marginBalance ?? state?.equity)}</b><small>Equity</small></span></div></div></div>
      <div className="als-live-row"><div><small>LAATSTE ACTIE</small><strong>{String(state?.lastAction || "MONITORING").replaceAll("_", " ")}</strong><em>{shortTime(state?.lastActionAt)}</em></div><div><small>VOLGENDE ACTIE</small><strong>{actionCopy(state?.recommendedAction)}</strong></div><div className={`als-engine ${state?.enabled ? "active" : "monitor"}`}><small>STATUS</small><strong>{engine.title}</strong><em>{engine.detail}</em></div></div>
      <footer className="als-footer"><i />Realtime bewaking van hedge, netto exposure, gross exposure en marginbuffer{state?.enabled ? ` · ${state.adoptedPositionCount ?? state.positionCount ?? 0} posities overgenomen` : " · automatische hedge is optioneel"}</footer>{message ? <p className="als-error">{message}</p> : null}
    </section>
    {infoOpen ? <div className="als-info-backdrop" role="presentation" onClick={() => setInfoOpen(false)}><section className="als-info-modal" role="dialog" aria-modal="true" aria-label="Available to Trade uitleg" onClick={(event) => event.stopPropagation()}><button type="button" className="als-info-close" onClick={() => setInfoOpen(false)}>×</button><h3>Available to Trade ≠ liquidatieveiligheid</h3><p><b>Available</b> laat zien hoeveel ruimte er voor nieuwe orders beschikbaar is. Het zegt niet rechtstreeks hoeveel afstand er nog tot liquidatie is.</p><p>Voor deze veiligheidsmonitor zijn vooral <b>Equity / Margin Balance</b>, <b>Maintenance Margin</b> en de daaruit bevestigde <b>Margin Buffer</b> relevant. Een hoge hedge-dekking kan bovendien nog steeds samengaan met hoge gross exposure.</p><button type="button" onClick={() => setInfoOpen(false)}>Begrepen</button></section></div> : null}
  </>, host);
}
