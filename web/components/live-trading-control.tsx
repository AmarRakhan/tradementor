"use client";

import { useEffect, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

type TradingStatus = "loading" | "off" | "on" | "blocked";

export function LiveTradingControl({ cloudReady }: { cloudReady: boolean }) {
  const [status, setStatus] = useState<TradingStatus>("loading");
  const [message, setMessage] = useState("Persoonlijke handelsstatus ophalen…");
  const [confirming, setConfirming] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!cloudReady) return;
    authenticatedRequest("/api/execution/status")
      .then((payload) => {
        const enabled = Boolean(payload.tradingEnabled);
        setStatus(enabled ? "on" : "off");
        setMessage(enabled ? "De cloud accepteert live handelsopdrachten voor dit account." : "Standaard uit. Er kunnen geen nieuwe echte orders worden geopend.");
      })
      .catch((reason) => {
        setStatus("blocked");
        setMessage(reason instanceof Error ? reason.message : "Handelsstatus kon niet worden gecontroleerd.");
      });
  }, [cloudReady]);

  async function prepareActivation() {
    setBusy(true);
    try {
      const result = await authenticatedRequest("/api/execution/preflight");
      if (!result.ready || !result.signatureVerified) throw new Error("De uitvoeringscontrole is niet volledig geslaagd.");
      setConfirming(true);
      setAccepted(false);
      setStatus("off");
      setMessage(`Agentwallet …${result.agentAddressSuffix} gecontroleerd · ${result.activePositions} actieve posities · ${result.remainingSlots} vrije plaatsen.`);
    } catch (reason) {
      setStatus("blocked");
      setMessage(reason instanceof Error ? reason.message : "Live handel kan nog niet worden vrijgegeven.");
    } finally {
      setBusy(false);
    }
  }

  async function setLive(enabled: boolean) {
    setBusy(true);
    try {
      const result = await authenticatedRequest("/api/execution/live", { method: "PUT", body: JSON.stringify({ enabled }) });
      setStatus(result.enabled ? "on" : "off");
      setConfirming(false);
      setAccepted(false);
      setMessage(result.enabled
        ? result.ordersEnabled ? "Live handel is actief. Scanneropdrachten kunnen echte orders uitvoeren." : "De persoonlijke schakelaar staat aan, maar de centrale productiepoort houdt orders nog tegen."
        : "Live handel is uitgeschakeld. Bestaande posities blijven zichtbaar en beschermbaar.");
    } catch (reason) {
      setStatus("blocked");
      setMessage(reason instanceof Error ? reason.message : "De handelsschakelaar kon niet worden bijgewerkt.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={`live-control ${status}`} aria-label="Live handel">
      <div className="live-control-heading"><div><span className="kicker">UITVOERING</span><strong>Live handel</strong></div><span className="live-state"><i />{status === "on" ? "AAN" : status === "loading" ? "CONTROLEREN" : "UIT"}</span></div>
      <p>{message}</p>
      {confirming ? (
        <div className="live-confirm">
          <label><input type="checkbox" checked={accepted} onChange={(event) => setAccepted(event.target.checked)} /><span>Ik begrijp dat de gekozen scanner daarna echte orders kan uitvoeren.</span></label>
          <div><button type="button" onClick={() => setConfirming(false)}>Annuleren</button><button type="button" className="danger-action" disabled={!accepted || busy} onClick={() => setLive(true)}>Live handel activeren</button></div>
        </div>
      ) : status === "on" ? (
        <button type="button" className="disable-live" disabled={busy} onClick={() => setLive(false)}>Live handel veilig uitschakelen</button>
      ) : (
        <button type="button" disabled={!cloudReady || busy} onClick={prepareActivation}>{busy ? "Controle wordt uitgevoerd…" : "Controleer en bereid activering voor"}</button>
      )}
    </section>
  );
}
