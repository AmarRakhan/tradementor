"use client";

import { useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

export function AsterStrategy2QuickControl({ snapshot, onChanged }: { snapshot: Record<string, unknown> | null; onChanged: () => void }) {
  const state = (snapshot?.strategy2 && typeof snapshot.strategy2 === "object" ? snapshot.strategy2 : {}) as Record<string, unknown>;
  const settings = (state.settings && typeof state.settings === "object" ? state.settings : {}) as Record<string, unknown>;
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [canaryRequired, setCanaryRequired] = useState(false);

  async function toggle() {
    setBusy(true); setMessage("");
    try {
      if (state.enabled) {
        await authenticatedRequest("/api/exchanges/aster/strategy2/stop", { method: "POST", body: JSON.stringify({ confirm: true }) });
        setMessage("Strategy 2 is veilig uitgeschakeld.");
      } else {
        const readiness = await authenticatedRequest("/api/exchanges/aster/strategy2/readiness") as Record<string, unknown>;
        if (readiness.liveReady !== true) {
          setCanaryRequired(readiness.softwareReady === true);
          setMessage(readiness.softwareReady === true ? "Eenmalige persoonlijke mini-canary is nog nodig." : "Niet alle persoonlijke live-controles zijn gereed.");
          return;
        }
        await authenticatedRequest("/api/exchanges/aster/strategy2/start", { method: "POST", body: JSON.stringify({ confirm: true, settings: { ...settings, mode: "live" } }) });
        setMessage("Strategy 2 is ingeschakeld.");
      }
      await Promise.resolve(onChanged());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Actie niet voltooid.");
    } finally { setBusy(false); }
  }

  async function canary() {
    setBusy(true); setMessage("De mini-canary opent maximaal US$ 10 en sluit direct na de bevestigde fill.");
    try {
      await authenticatedRequest("/api/exchanges/aster/strategy2/canary", { method: "POST", body: JSON.stringify({ confirm: true, notional_usd: 10 }) });
      setCanaryRequired(false); setMessage("Mini-canary geslaagd. Je kunt de live bot nu inschakelen.");
      await Promise.resolve(onChanged());
    } catch (error) { setMessage(error instanceof Error ? error.message : "Mini-canary niet voltooid."); }
    finally { setBusy(false); }
  }

  return <div className={`strategy-quick-control ${state.enabled ? "enabled" : state.liveReady ? "ready" : "locked"}`}>
    <div><span>STRATEGY 2 LIVE BOT</span><strong>{state.enabled ? "AAN" : "UIT"}</strong><small>{state.enabled ? "Bot draait" : state.liveReady ? "Klaar om te starten" : "Persoonlijke controle nodig"}</small></div>
    <button type="button" role="switch" aria-checked={Boolean(state.enabled)} disabled={busy} onClick={toggle}>{busy ? "Controleren…" : state.enabled ? "Uitschakelen" : "Inschakelen"}</button>
    {canaryRequired && <button type="button" className="canary-action" disabled={busy} onClick={canary}>Voer eenmalige mini-canary van US$ 10 uit</button>}
    {message && <p>{message}</p>}
  </div>;
}
