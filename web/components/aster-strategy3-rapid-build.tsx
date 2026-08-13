"use client";

import { useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

export function AsterStrategy3RapidBuild({ snapshot, onChanged }: { snapshot: Record<string, unknown> | null; onChanged: () => void }) {
  const state = (snapshot?.strategy3 && typeof snapshot.strategy3 === "object" ? snapshot.strategy3 : {}) as Record<string, unknown>;
  const settings = (state.settings && typeof state.settings === "object" ? state.settings : {}) as Record<string, unknown>;
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  if (state.enabled !== true) return null;
  const target = Number(settings.maximumPositions || 0);
  const active = Number(state.activeTrades || 0);
  const accountActive = Number(state.accountActivePositions || 0);
  const baseNotional = Number(settings.baseNotional || 0);
  const takeProfit = Number(settings.takeProfitPct || 0);
  const leverage = Number(settings.leverage || 0);

  async function start() {
    if (!confirmed) return;
    setBusy(true);
    setMessage("Aster bevestigt iedere startpositie afzonderlijk…");
    try {
      const result = await authenticatedRequest("/api/exchanges/aster/strategy3/rapid-build", { method: "POST", body: JSON.stringify({ confirm: true }) }) as Record<string, unknown>;
      const batch = (result.batch && typeof result.batch === "object" ? result.batch : {}) as Record<string, unknown>;
      setMessage(`Eerste batch: ${Number(batch.ordersSent || 0)} positie(s) bevestigd. De cloud bouwt verder tot het doel of een risicogrens.`);
      setConfirmed(false);
      await Promise.resolve(onChanged());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Snelle startopbouw is veilig gestopt.");
    } finally { setBusy(false); }
  }

  return <article className="strategy-card strategy3-rapid-build">
    <span className="kicker">HANDMATIGE STARTOPBOUW</span>
    <h3>Vrije plekken versneld vullen</h3>
    <p><strong>Effectieve live-configuratie (server):</strong> US$ {baseNotional.toLocaleString("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} per positie · TP {takeProfit.toFixed(2)}% · {leverage}× · maximaal {target} Aster-posities accountbreed.</p>
    <p><strong>{accountActive} van {target}</strong> Aster-posities accountbreed actief; daarvan beheert Strategy 3 er {active}. LONG en SHORT worden zo gelijk mogelijk opgebouwd.</p>
    <label className="rapid-build-consent"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} /><span>Ik bevestig snelle live-opbouw. Iedere order blijft afzonderlijk gecontroleerd en stopt bij onzekerheid of verhoogd risico.</span></label>
    <button type="button" className="start-action" disabled={busy || !confirmed || target <= 0 || accountActive >= target} onClick={start}>{busy ? "Startbatch uitvoeren…" : accountActive >= target && target > 0 ? "Accountlimiet bereikt" : "Startopbouw nu"}</button>
    {message && <p className="strategy-message">{message}</p>}
  </article>;
}
