"use client";

import { useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

type TradeContext = { exchange: string; symbol: string; side: string; size: number; entry: number; mark: number; pnl: number; leverage: number; dcaCount: number; status: "active" | "closed" };

export function TradeReportControl({ trade }: { trade: TradeContext }) {
  const [open, setOpen] = useState(false), [description, setDescription] = useState(""), [busy, setBusy] = useState(false), [sent, setSent] = useState(false), [error, setError] = useState("");
  async function submit() {
    if (description.trim().length < 5) { setError("Vertel in een paar woorden wat je vreemd vindt."); return; }
    setBusy(true); setError("");
    try {
      const technicalContext = [`Exchange: ${trade.exchange}`, `Pair: ${trade.symbol}`, `Richting: ${trade.side}`, `Status: ${trade.status}`, `Grootte: ${trade.size}`, `Instap: ${trade.entry}`, `Actueel/sluitprijs: ${trade.mark}`, `PnL: ${trade.pnl}`, `Leverage: ${trade.leverage}`, `DCA: ${trade.dcaCount}`, `Gemeld op: ${new Date().toISOString()}`].join("\n");
      await authenticatedRequest("/api/feedback", { method: "POST", body: JSON.stringify({ category: "trade_anomaly", title: `Vreemde trade: ${trade.symbol} ${trade.side}`, description: `${description.trim()}\n\nAutomatisch meegestuurde tradecontext:\n${technicalContext}`, screen: `${trade.exchange} positions`, app_version: "web-test", build_number: "3", device_model: navigator.userAgent.slice(0, 180), android_version: "web-pwa" }) });
      setSent(true);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "De melding kon niet worden verstuurd."); }
    finally { setBusy(false); }
  }
  function close() { setOpen(false); setSent(false); setDescription(""); setError(""); }
  return <><button type="button" className="trade-report-trigger" onClick={() => setOpen(true)} aria-label={`Meld iets vreemds over ${trade.symbol}`} title="Iets vreemds melden">?</button>{open&&<div className="trade-report-layer" role="presentation" onMouseDown={(event) => { if(event.target===event.currentTarget) close(); }}><section className="trade-report-dialog" role="dialog" aria-modal="true" aria-labelledby="trade-report-title">{sent ? <div className="trade-report-success"><i>✓</i><h3 id="trade-report-title">Uw aanvraag is verstuurd</h3><p>We nemen de melding zo snel mogelijk door. De status en ons antwoord verschijnen bij Mijn meldingen.</p><button type="button" onClick={close}>Gereed</button></div> : <><header><div><span>TRADE CONTROLEREN</span><h3 id="trade-report-title">Wat vind je vreemd aan {trade.symbol}?</h3><p>TradeMentor stuurt de zichtbare positiegegevens automatisch mee. API-sleutels en wachtwoorden horen nooit in deze melding.</p></div><button type="button" onClick={close} aria-label="Sluiten">×</button></header><div className="trade-report-context"><b>{trade.exchange.toUpperCase()} · {trade.symbol}</b><span>{trade.side} · {trade.leverage}× · PnL {trade.pnl >= 0 ? "+" : ""}{trade.pnl.toFixed(2)}</span></div><label>Jouw uitleg<textarea rows={5} maxLength={1600} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Bijvoorbeeld: deze positie had volgens mij al verkocht of bijgekocht moeten worden…" /></label>{error&&<p className="trade-report-error">{error}</p>}<footer><button type="button" onClick={close}>Annuleren</button><button type="button" disabled={busy} onClick={submit}>{busy ? "Versturen…" : "Melding versturen"}</button></footer></>}</section></div>}</>;
}
