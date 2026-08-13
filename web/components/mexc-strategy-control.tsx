"use client";

import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

type FieldState = {
  mode: "paper" | "live";
  initialOrder: string;
  takeProfit: string;
  maximumDca: string;
  timeframe: string;
  dcaSpacing: string;
  hedge: boolean;
  emergencyHedge: boolean;
  emergencyEquity: string;
  rescue: boolean;
  rescueOrder: string;
  availableBuffer: string;
  maxMarginRatio: string;
  minLiquidationDistance: string;
};

const defaults: FieldState = {
  mode: "paper", initialOrder: "70", takeProfit: "0.50", maximumDca: "40", timeframe: "3m", dcaSpacing: "0.50",
  hedge: true, emergencyHedge: true, emergencyEquity: "95", rescue: true, rescueOrder: "10", availableBuffer: "10",
  maxMarginRatio: "60", minLiquidationDistance: "8",
};

const number = (value: unknown, fallback: number) => Number.isFinite(Number(value)) ? Number(value) : fallback;

export function MexcStrategyControl({ snapshot, cloudReady, onChanged }: {
  snapshot: Record<string, unknown> | null;
  cloudReady: boolean;
  onChanged: () => void;
}) {
  const [fields, setFields] = useState<FieldState>(defaults);
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [tone, setTone] = useState<"ok" | "warn" | "error">("warn");

  useEffect(() => {
    const value = snapshot?.automationSettings;
    if (!value || typeof value !== "object") return;
    const settings = value as Record<string, unknown>;
    setFields({
      mode: settings.mode === "live" ? "live" : "paper",
      initialOrder: String(number(settings.initial_order_notional, 70)),
      takeProfit: String(number(settings.take_profit, .005) * 100),
      maximumDca: String(number(settings.maximum_dca_orders, 40)),
      timeframe: String(settings.dca_timeframe || "3m"),
      dcaSpacing: String(number(settings.dca_spacing, .005) * 100),
      hedge: settings.hedge_enabled !== false,
      emergencyHedge: settings.emergency_hedge_enabled !== false,
      emergencyEquity: String(number(settings.emergency_equity_trigger, 95)),
      rescue: settings.rescue_enabled !== false,
      rescueOrder: String(number(settings.rescue_order_notional, 10)),
      availableBuffer: String(number(settings.minimum_available_buffer, 10)),
      maxMarginRatio: String(number(settings.maximum_margin_ratio, .6) * 100),
      minLiquidationDistance: String(number(settings.minimum_liquidation_distance, .08) * 100),
    });
  }, [snapshot?.automationSettings]);

  const settings = useMemo(() => ({
    strategyVersion: "hedge_dca_v3",
    mode: fields.mode,
    tradingPair: "BTC_USDT",
    leverage: 200,
    marginMode: "cross",
    initialOrderNotional: number(fields.initialOrder, 0),
    takeProfit: number(fields.takeProfit, 0) / 100,
    maximumDcaOrders: Math.round(number(fields.maximumDca, 0)),
    dcaTimeframe: fields.timeframe,
    dcaSpacing: number(fields.dcaSpacing, 0) / 100,
    hedgeEnabled: fields.hedge,
    emergencyHedgeEnabled: fields.emergencyHedge,
    emergencyEquityTrigger: number(fields.emergencyEquity, 0),
    emergencyHedgeRatio: 1,
    rescueEnabled: fields.rescue,
    rescueOrderNotional: number(fields.rescueOrder, 0),
    rescueTakeProfit: .005,
    maxFrozenCycles: 1,
    classicStopLoss: false,
    minimumAvailableBuffer: number(fields.availableBuffer, 0),
    maximumMarginRatio: number(fields.maxMarginRatio, 0) / 100,
    minimumLiquidationDistance: number(fields.minLiquidationDistance, 0) / 100,
    slippageTolerance: .001,
    assumedTakerFee: .0004,
    apiRetryLimit: 2,
    rescueRequiresIndependentAccount: true,
  }), [fields]);

  async function execute(kind: "save" | "simulate" | "start" | "stop") {
    setBusy(true); setMessage("");
    try {
      const path = kind === "save" ? "/api/exchanges/mexc/automation/settings" : `/api/exchanges/mexc/automation/${kind}`;
      const method = kind === "save" ? "PUT" : "POST";
      const body = kind === "stop" ? { confirm: true } : kind === "start" ? { confirm: true, settings } : { settings: kind === "simulate" ? { ...settings, mode: "paper" } : settings };
      const result = await authenticatedRequest(path, { method, body: JSON.stringify(body) });
      const action = result.action ? ` · ${result.action}` : "";
      setMessage(kind === "simulate" ? `Simulatie geslaagd${action}: ${result.reason || "geen risicovolle actie"}` : kind === "start" ? "Automatisering gestart; de veilige cloudscheduler neemt de monitoring over." : kind === "stop" ? "Nieuwe exposure gestopt; bescherming blijft actief tot het account vlak is." : "Instellingen persoonlijk opgeslagen.");
      setTone(kind === "stop" ? "warn" : "ok");
      onChanged();
    } catch (reason) {
      setTone("error");
      setMessage(reason instanceof Error ? reason.message : "De strategie-opdracht is niet gelukt.");
    } finally { setBusy(false); }
  }

  const automationOn = Boolean(snapshot?.automationEnabled);
  const liveEnabled = Boolean(snapshot?.liveEnabled);
  const ordersEnabled = Boolean(snapshot?.ordersEnabled) && Boolean(snapshot?.automationExecutionEnabled);
  return (
    <article className="strategy-card strategy-control-card">
      <div className="strategy-title-row"><div><span className="kicker">ACTIEVE STRATEGIE</span><h2>Hedge DCA V3</h2></div><span className={`strategy-state ${automationOn ? "on" : ""}`}>{automationOn ? "ACTIEF" : "GESTOPT"}</span></div>
      <p>{String(snapshot?.automationReason || "LONG en SHORT worden als afzonderlijke cycli bewaakt.")}</p>
      <div className="strategy-facts"><span>BTCUSDT</span><span>Cross 200×</span><span>{fields.timeframe}</span><span>{fields.mode.toUpperCase()}</span></div>
      <button type="button" className="expand-settings" onClick={() => setExpanded((value) => !value)}>{expanded ? "Instellingen sluiten" : "Strategie instellen"}</button>
      {expanded && <div className="strategy-settings">
        <div className="mode-switch"><button type="button" className={fields.mode === "paper" ? "active" : ""} onClick={() => setFields({ ...fields, mode: "paper" })}>Paper</button><button type="button" className={fields.mode === "live" ? "active danger" : ""} onClick={() => setFields({ ...fields, mode: "live" })}>Echt geld</button></div>
        <div className="settings-grid">
          <NumberField label="Eerste order (USD)" value={fields.initialOrder} onChange={(value) => setFields({ ...fields, initialOrder: value })} />
          <NumberField label="Take profit (%)" value={fields.takeProfit} onChange={(value) => setFields({ ...fields, takeProfit: value })} />
          <NumberField label="Max. DCA-orders" value={fields.maximumDca} onChange={(value) => setFields({ ...fields, maximumDca: value })} />
          <label>Execution timeframe<select value={fields.timeframe} onChange={(event) => setFields({ ...fields, timeframe: event.target.value })}>{["1m","3m","5m","15m","30m","1h"].map((item) => <option key={item}>{item}</option>)}</select></label>
          <NumberField label="DCA-afstand (%)" value={fields.dcaSpacing} onChange={(value) => setFields({ ...fields, dcaSpacing: value })} />
          <NumberField label="Beschikbare buffer (USD)" value={fields.availableBuffer} onChange={(value) => setFields({ ...fields, availableBuffer: value })} />
          <NumberField label="Max. margin ratio (%)" value={fields.maxMarginRatio} onChange={(value) => setFields({ ...fields, maxMarginRatio: value })} />
          <NumberField label="Min. liquidatieafstand (%)" value={fields.minLiquidationDistance} onChange={(value) => setFields({ ...fields, minLiquidationDistance: value })} />
          <NumberField label="Noodrem bij equity (USD)" value={fields.emergencyEquity} onChange={(value) => setFields({ ...fields, emergencyEquity: value })} />
          <NumberField label="Rescue-order (USD)" value={fields.rescueOrder} onChange={(value) => setFields({ ...fields, rescueOrder: value })} />
        </div>
        <label className="compact-toggle"><input type="checkbox" checked={fields.hedge} onChange={(event) => setFields({ ...fields, hedge: event.target.checked })} />Dynamische hedge</label>
        <label className="compact-toggle"><input type="checkbox" checked={fields.emergencyHedge} onChange={(event) => setFields({ ...fields, emergencyHedge: event.target.checked })} />Emergency hedge</label>
        <label className="compact-toggle"><input type="checkbox" checked={fields.rescue} onChange={(event) => setFields({ ...fields, rescue: event.target.checked })} />Rescue-cyclus</label>
        <div className="strategy-actions"><button type="button" disabled={busy || !cloudReady} onClick={() => execute("save")}>Opslaan</button><button type="button" disabled={busy || !cloudReady} onClick={() => execute("simulate")}>Veilig simuleren</button>{automationOn ? <button type="button" className="stop-action" disabled={busy} onClick={() => execute("stop")}>Nieuwe exposure stoppen</button> : <button type="button" className="start-action" disabled={busy || fields.mode !== "live" || !liveEnabled || !ordersEnabled} onClick={() => execute("start")}>Live strategie starten</button>}</div>
        {fields.mode === "live" && (!liveEnabled || !ordersEnabled) && <p className="inline-warning">Activeer eerst MEXC live handel én wacht tot de centrale productiepoorten groen zijn.</p>}
      </div>}
      {message && <p className={`strategy-message ${tone}`}>{message}</p>}
    </article>
  );
}

function NumberField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label>{label}<input inputMode="decimal" value={value} onChange={(event) => onChange(event.target.value.replace(",", "."))} /></label>;
}
