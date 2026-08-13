"use client";

import { useEffect, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

type Exchange = "hyperliquid" | "mexc";
type Status = "loading" | "off" | "on" | "blocked";

export function ExchangeLiveControl({ exchange, cloudReady, snapshot, onChanged }: {
  exchange: Exchange;
  cloudReady: boolean;
  snapshot?: Record<string, unknown> | null;
  onChanged?: () => void;
}) {
  const [status, setStatus] = useState<Status>("loading");
  const [ordersEnabled, setOrdersEnabled] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Persoonlijke handelsstatus controleren…");

  useEffect(() => {
    if (!cloudReady) return;
    const path = exchange === "mexc" ? "/api/exchanges/mexc" : "/api/execution/status";
    authenticatedRequest(path)
      .then((payload) => {
        const enabled = Boolean(exchange === "mexc" ? payload.liveEnabled : payload.tradingEnabled);
        setStatus(enabled ? "on" : "off");
        setOrdersEnabled(Boolean(payload.ordersEnabled));
        setMessage(enabled
          ? payload.ordersEnabled ? "Persoonlijke én centrale orderpoort zijn actief." : "Persoonlijke schakelaar staat aan; de centrale productiepoort houdt nieuwe orders nog tegen."
          : "Standaard uit. Er kunnen geen nieuwe echte orders worden geopend.");
      })
      .catch((reason) => {
        setStatus("blocked");
        setMessage(reason instanceof Error ? reason.message : "Handelsstatus kon niet worden gecontroleerd.");
      });
  }, [cloudReady, exchange, snapshot]);

  async function prepare() {
    setBusy(true);
    try {
      if (exchange === "hyperliquid") {
        const result = await authenticatedRequest("/api/execution/preflight");
        if (!result.ready || !result.signatureVerified) throw new Error("De Hyperliquid-uitvoeringscontrole is niet volledig geslaagd.");
        setMessage(`Agentwallet …${result.agentAddressSuffix} gecontroleerd · ${result.activePositions} actief · ${result.remainingSlots} vrije plaatsen.`);
      } else {
        const result = await authenticatedRequest("/api/exchanges/mexc");
        if (!result.configured || !result.liveReady) throw new Error("MEXC is nog niet klaar: controleer API, Hedge Mode, Cross 200× en beschikbare marge.");
        setMessage(`MEXC gecontroleerd · Cross ${result.executionLeverage}× · ${result.openBtcPositions} BTC-posities.`);
      }
      setConfirming(true);
      setAccepted(false);
      setStatus("off");
    } catch (reason) {
      setStatus("blocked");
      setMessage(reason instanceof Error ? reason.message : "Live handel kan nog niet worden voorbereid.");
    } finally {
      setBusy(false);
    }
  }

  async function setLive(enabled: boolean) {
    setBusy(true);
    try {
      const path = exchange === "mexc" ? "/api/exchanges/mexc/live" : "/api/execution/live";
      const body = exchange === "mexc" ? { enabled, confirm: enabled } : { enabled };
      const result = await authenticatedRequest(path, { method: "PUT", body: JSON.stringify(body) });
      const active = Boolean(exchange === "mexc" ? result.liveEnabled : result.enabled);
      setStatus(active ? "on" : "off");
      setOrdersEnabled(Boolean(result.ordersEnabled));
      setConfirming(false);
      setAccepted(false);
      setMessage(active
        ? result.ordersEnabled ? "Live uitvoering is actief. Strategie-opdrachten kunnen echte orders plaatsen." : "Persoonlijke schakelaar staat aan; de centrale productiepoort blokkeert nog nieuwe orders."
        : "Live uitvoering is veilig uitgeschakeld. Bestaande posities blijven zichtbaar en beschermbaar.");
      onChanged?.();
    } catch (reason) {
      setStatus("blocked");
      setMessage(reason instanceof Error ? reason.message : "De handelsschakelaar kon niet worden bijgewerkt.");
    } finally {
      setBusy(false);
    }
  }

  const name = exchange === "mexc" ? "MEXC" : "Hyperliquid";
  return (
    <section className={`live-control ${status}`} aria-label={`${name} live handel`}>
      <div className="live-control-heading"><div><span className="kicker">ECHT GELD</span><strong>{name} live handel</strong></div><span className="live-state"><i />{status === "on" ? "AAN" : status === "loading" ? "CONTROLEREN" : "UIT"}</span></div>
      <p>{message}</p>
      {status === "on" && !ordersEnabled && <span className="central-lock">CENTRALE ORDERPOORT NOG VERGRENDELD</span>}
      {confirming ? (
        <div className="live-confirm">
          <label><input type="checkbox" checked={accepted} onChange={(event) => setAccepted(event.target.checked)} /><span>Ik begrijp dat de actieve strategie daarna echte orders met echt geld kan uitvoeren.</span></label>
          <div><button type="button" onClick={() => setConfirming(false)}>Annuleren</button><button type="button" className="danger-action" disabled={!accepted || busy} onClick={() => setLive(true)}>Bewust activeren</button></div>
        </div>
      ) : status === "on" ? (
        <button type="button" className="disable-live" disabled={busy} onClick={() => setLive(false)}>Live handel veilig uitschakelen</button>
      ) : (
        <button type="button" disabled={!cloudReady || busy} onClick={prepare}>{busy ? "Controle wordt uitgevoerd…" : "Controleer en bereid activering voor"}</button>
      )}
    </section>
  );
}
