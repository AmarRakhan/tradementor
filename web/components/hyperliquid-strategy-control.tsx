"use client";

import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

type Fields = {
  baseOrder: string; safetyOrders: string; longDeviation: string; shortDeviation: string;
  maximum: string; cooldown: string; target: string; topUniverse: string;
  entryMode: "direct" | "bollinger"; leverage: string; stopLoss: boolean; stopLossPercent: string;
};

const defaults: Fields = {
  baseOrder: "20", safetyOrders: "3", longDeviation: "2", shortDeviation: "8",
  maximum: "20", cooldown: "15", target: "10", topUniverse: "50",
  entryMode: "bollinger", leverage: "5", stopLoss: false, stopLossPercent: "25",
};
const number = (value: unknown, fallback: number) => Number.isFinite(Number(value)) ? Number(value) : fallback;

export function HyperliquidStrategyControl({ cloudReady, onChanged }: { cloudReady: boolean; onChanged: () => void }) {
  const [fields, setFields] = useState<Fields>(defaults);
  const [expanded, setExpanded] = useState(false);
  const [scanner, setScanner] = useState<Record<string, unknown> | null>(null);
  const [cycle, setCycle] = useState<Record<string, unknown> | null>(null);
  const [liveEnabled, setLiveEnabled] = useState(false);
  const [ordersEnabled, setOrdersEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [tone, setTone] = useState<"ok" | "warn" | "error">("warn");

  async function load() {
    if (!cloudReady) return;
    try {
      const [preflight, status, cycleStatus] = await Promise.all([
        authenticatedRequest("/api/execution/status"),
        authenticatedRequest("/api/exchanges/hyperliquid/scanner/status"),
        authenticatedRequest("/api/exchanges/hyperliquid/cycle/status", { method: "POST", body: "{}" }),
      ]);
      setScanner(status); setCycle(cycleStatus);
      setLiveEnabled(Boolean(preflight.tradingEnabled));
      setOrdersEnabled(Boolean(preflight.ordersEnabled));
      const raw = status.scannerSettings as Record<string, unknown> | undefined;
      if (raw) setFields({
        baseOrder: String(number(raw.base_order_usd, 20)), safetyOrders: String(number(raw.max_safety_orders, 3)),
        longDeviation: String(number(raw.long_deviation_percent, 2)), shortDeviation: String(number(raw.short_deviation_percent, 8)),
        maximum: String(number(raw.max_active_deals, 20)), cooldown: String(number(raw.cooldown_minutes, 15)),
        target: String(number(raw.portfolio_target_percent, 10)), topUniverse: String(number(raw.top_universe_size, 50)),
        entryMode: raw.entry_mode === "direct" ? "direct" : "bollinger", leverage: String(number(raw.leverage, 5)),
        stopLoss: raw.stop_loss_enabled === true, stopLossPercent: String(number(raw.stop_loss_percent, 25)),
      });
    } catch (reason) {
      setTone("error"); setMessage(reason instanceof Error ? reason.message : "DCA Pulse kon niet worden geladen.");
    }
  }

  useEffect(() => { load(); }, [cloudReady]);

  const settings = useMemo(() => ({
    strategyId: "strategy_3", baseOrderUsd: number(fields.baseOrder, 0),
    maxSafetyOrders: Math.round(number(fields.safetyOrders, 0)),
    longDeviationPercent: number(fields.longDeviation, 0), shortDeviationPercent: number(fields.shortDeviation, 0),
    maxActiveDeals: Math.round(number(fields.maximum, 0)), cooldownMinutes: Math.round(number(fields.cooldown, 0)),
    portfolioTargetPercent: number(fields.target, 0), topUniverseSize: Math.round(number(fields.topUniverse, 0)),
    entryMode: fields.entryMode, leverage: Math.round(number(fields.leverage, 1)),
    stopLossEnabled: fields.stopLoss, stopLossPercent: number(fields.stopLossPercent, 25),
  }), [fields]);

  async function execute(kind: "save" | "simulate" | "start" | "stop") {
    setBusy(true); setMessage("");
    try {
      const path = `/api/exchanges/hyperliquid/scanner/${kind === "save" ? "settings" : kind}`;
      const body = kind === "stop" ? { confirm: true } : kind === "start" ? { confirm: true, settings } : { settings };
      const result = await authenticatedRequest(path, { method: kind === "save" ? "PUT" : "POST", body: JSON.stringify(body) });
      if (kind !== "simulate") setScanner(result);
      const actions = Array.isArray(result.actions) ? result.actions.length : 0;
      setTone(kind === "stop" ? "warn" : "ok");
      setMessage(kind === "simulate" ? `Veilige simulatie klaar: ${result.scannedMarkets || 0} markten, ${result.candidateCount || 0} kandidaten en ${actions} geplande acties. Er is niets gekocht.` : kind === "start" ? "DCA Pulse is gestart. De cloudscheduler blijft ook zonder geopende website controleren." : kind === "stop" ? "DCA Pulse is gestopt. Er worden geen nieuwe orders of bijkopen geplaatst." : "Alle DCA-instellingen en de ene capaciteitswaarde zijn persoonlijk opgeslagen.");
      onChanged(); await load();
    } catch (reason) {
      setTone("error"); setMessage(reason instanceof Error ? reason.message : "De scanneropdracht is niet gelukt.");
    } finally { setBusy(false); }
  }

  async function updateCycle() {
    setBusy(true); setMessage("");
    try {
      const percentage = Math.max(1, Math.min(1000, number(fields.target, 10)));
      const active = cycle?.status === "active";
      const result = await authenticatedRequest(active ? "/api/exchanges/hyperliquid/cycle/target" : "/api/exchanges/hyperliquid/cycle/start", {
        method: active ? "PUT" : "POST", body: JSON.stringify({ target_percentage: percentage }),
      });
      setCycle(result); setTone("ok"); setMessage(active ? "Het cyclusdoel is verhoogd." : "De portfoliocyclus is gestart vanaf de actuele exchange-waarde.");
    } catch (reason) { setTone("error"); setMessage(reason instanceof Error ? reason.message : "De cyclus kon niet worden bijgewerkt."); }
    finally { setBusy(false); }
  }

  const scannerOn = Boolean(scanner?.scannerEnabled);
  const cycleActive = cycle?.status === "active";
  return <article className="strategy-card strategy-control-card">
    <div className="strategy-title-row"><div><span className="kicker">ACTIEVE STRATEGIE</span><h2>DCA Pulse</h2></div><span className={`strategy-state ${scannerOn ? "on" : ""}`}>{scannerOn ? "CLOUDSCAN ACTIEF" : "GESTOPT"}</span></div>
    <p>{String(scanner?.scannerReason || "Multipair DCA met gescheiden LONG/SHORT-afstanden en servergestuurde balanscontrole.")}</p>
    <div className="strategy-facts"><span>{Number(scanner?.scannerScannedMarkets || 0)} gescand</span><span>{Number(scanner?.scannerCandidateCount || 0)} kandidaten</span><span>{fields.maximum} max.</span><span>{fields.entryMode === "direct" ? "Direct" : "Bollinger"}</span></div>
    {cycleActive && <div className="cycle-progress"><div><span>Start</span><strong>{money(cycle?.startPortfolioValue)}</strong></div><div><span>Huidig</span><strong>{money(cycle?.currentPortfolioValue)}</strong></div><div><span>Doel</span><strong>{money(cycle?.targetPortfolioValue)}</strong></div><i style={{ width: `${Math.min(100, Number(cycle?.progressPercentage || 0))}%` }} /></div>}
    <button type="button" className="expand-settings" onClick={() => setExpanded((value) => !value)}>{expanded ? "Instellingen sluiten" : "DCA Pulse instellen"}</button>
    {expanded && <div className="strategy-settings">
      <div className="settings-grid">
        <NumberField label="Basisorder (USD)" value={fields.baseOrder} onChange={(value) => setFields({ ...fields, baseOrder: value })} />
        <NumberField label="Max. bijkopen per pair" value={fields.safetyOrders} onChange={(value) => setFields({ ...fields, safetyOrders: value })} />
        <NumberField label="LONG-afstand (%)" value={fields.longDeviation} onChange={(value) => setFields({ ...fields, longDeviation: value })} />
        <NumberField label="SHORT-afstand (%)" value={fields.shortDeviation} onChange={(value) => setFields({ ...fields, shortDeviation: value })} />
        <NumberField label="Max. actieve deals" value={fields.maximum} onChange={(value) => setFields({ ...fields, maximum: value })} />
        <NumberField label="Cloudcontrole (minuten)" value={fields.cooldown} onChange={(value) => setFields({ ...fields, cooldown: value })} />
        <NumberField label="Portfoliodoel (%)" value={fields.target} onChange={(value) => setFields({ ...fields, target: value })} />
        <NumberField label="CoinMarketCap top-N" value={fields.topUniverse} onChange={(value) => setFields({ ...fields, topUniverse: value })} />
        <label>Instapregel<select value={fields.entryMode} onChange={(event) => setFields({ ...fields, entryMode: event.target.value as Fields["entryMode"] })}><option value="bollinger">24u beweging + Bollinger</option><option value="direct">Direct hardste beweging</option></select></label>
        <NumberField label="Max. gevraagde hefboom" value={fields.leverage} onChange={(value) => setFields({ ...fields, leverage: value })} />
      </div>
      <label className="compact-toggle"><input type="checkbox" checked={fields.stopLoss} onChange={(event) => setFields({ ...fields, stopLoss: event.target.checked })} />Stop-loss per positie plaatsen</label>
      {fields.stopLoss && <NumberField label="Stop-loss tegenbeweging (%)" value={fields.stopLossPercent} onChange={(value) => setFields({ ...fields, stopLossPercent: value })} />}
      <p className="inline-warning">Simuleren koopt nooit. Live starten kan alleen als jouw agentwallet, persoonlijke live-schakelaar en centrale productiepoort alle drie groen zijn.</p>
      <div className="strategy-actions"><button type="button" disabled={busy} onClick={() => execute("save")}>Opslaan</button><button type="button" disabled={busy} onClick={() => execute("simulate")}>Veilig simuleren</button><button type="button" disabled={busy} onClick={updateCycle}>{cycleActive ? "Doel verhogen" : "Cyclus vastleggen"}</button>{scannerOn ? <button type="button" className="stop-action" disabled={busy} onClick={() => execute("stop")}>Scanner stoppen</button> : <button type="button" className="start-action" disabled={busy || !liveEnabled || !ordersEnabled} onClick={() => execute("start")}>Scan & Buy starten</button>}</div>
      {!scannerOn && (!liveEnabled || !ordersEnabled) && <p className="inline-warning">Activeer eerst Hyperliquid live handel en wacht tot de centrale productiepoort groen is.</p>}
    </div>}
    {message && <p className={`strategy-message ${tone}`}>{message}</p>}
  </article>;
}

function NumberField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label>{label}<input inputMode="decimal" value={value} onChange={(event) => onChange(event.target.value.replace(",", "."))} /></label>;
}

function money(value: unknown) {
  const amount = Number(value);
  return Number.isFinite(amount) ? new Intl.NumberFormat("nl-NL", { style: "currency", currency: "USD" }).format(amount) : "—";
}
