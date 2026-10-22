"use client";

import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { WEBAPP_BUILD_NUMBER } from "@/lib/app-version";
import { recoveryLadder, validateRecoverySettings } from "@/lib/short-recovery.mjs";

// SHORT Recovery 2.0 settings + status. Saving only stores settings; the server worker decides and
// places every order through the existing Auto Hedge engine. This component holds no order logic.

type Plan = { enabled: boolean; steps: number; totalPct: string; stepPct?: string };
type AutoHedgeLike = {
  enabled: boolean;
  pairs?: Array<Record<string, unknown>>;
  shortRecoveryPlan?: Plan;
  shortRecoveryExecutionEnabled?: boolean;
};

const GOLD = "#d6b75c";
const card: React.CSSProperties = {
  backfaceVisibility: "hidden", padding: 18, border: "1px solid #b89343", borderRadius: 20,
  background: "#111b18", color: "#e8dfc7", minHeight: 300,
};
const field: React.CSSProperties = { width: "100%", padding: 8, borderRadius: 8, color: "white", background: "#25332d", border: "1px solid #3b4d43" };
const button: React.CSSProperties = { border: "1px solid #bd9650", borderRadius: 10, padding: "9px 12px", color: "#e7c66b", background: "#17261d" };

export function ShortRecoveryCard({ state, onSaved }: { state: AutoHedgeLike; onSaved: (next: AutoHedgeLike) => void }) {
  const plan = state.shortRecoveryPlan ?? { enabled: false, steps: 4, totalPct: "8" };
  const live = state.shortRecoveryExecutionEnabled === true;
  const [flipped, setFlipped] = useState(false);
  const [enabled, setEnabled] = useState(plan.enabled);
  const [steps, setSteps] = useState(String(plan.steps));
  const [totalPct, setTotalPct] = useState(String(plan.totalPct));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    setEnabled(plan.enabled); setSteps(String(plan.steps)); setTotalPct(String(plan.totalPct));
  }, [plan.enabled, plan.steps, plan.totalPct]);

  const check = validateRecoverySettings(steps, totalPct);
  const ladder = useMemo(() => recoveryLadder(steps, totalPct), [steps, totalPct]);
  const dirty = enabled !== plan.enabled || steps !== String(plan.steps) || totalPct !== String(plan.totalPct);

  async function save() {
    if (enabled && !check.ok) { setError(check.message); return; }
    // Switching OFF always works, even with half-typed inputs: keep the last saved values.
    const payload = check.ok
      ? { enabled, steps: check.steps, totalPct: String(check.totalPct) }
      : { enabled: false, steps: plan.steps, totalPct: String(plan.totalPct) };
    setSaving(true); setError(""); setMessage("");
    try {
      const next = await authenticatedRequest("/api/exchanges/aster/position-loss-auto-hedge/short-recovery", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload, clientBuild: String(WEBAPP_BUILD_NUMBER) }),
      }) as AutoHedgeLike;
      onSaved(next);
      setMessage(enabled ? "Opgeslagen · de bot past dit toe vanaf de volgende cyclus." : "Opgeslagen · SHORT Recovery staat UIT; posities worden weer 1:1 gehedged.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Opslaan mislukt");
    } finally {
      setSaving(false);
    }
  }

  const fmt = (n: number, d = 2) => n.toLocaleString("nl-NL", { maximumFractionDigits: d });

  return <section aria-label="SHORT Recovery 2.0" style={{ margin: "16px 0", perspective: 1200 }}>
    <div style={{ position: "relative", minHeight: flipped ? 300 : 330 }}>
      <div style={{ position: "relative", transformStyle: "preserve-3d", transform: flipped ? "rotateY(180deg)" : "rotateY(0)", transition: "transform .65s ease" }}>
        <div style={card}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <strong style={{ color: GOLD }}>SHORT RECOVERY 2.0</strong>
            <span style={{ fontSize: 11, opacity: .85 }}>{live ? "LIVE" : "TESTMODUS · geen orders"}</span>
          </div>
          <p style={{ fontSize: 12, opacity: .8, margin: "6px 0 10px" }}>
            Bouwt een Auto Hedge-SHORT in stappen af als de koers daalt. Leeg = automatisch weer 100% hedgen.
          </p>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} disabled={saving || (!state.enabled && !enabled)} />
            <span>SHORT Recovery {enabled ? "AAN" : "UIT"}{!state.enabled ? " · zet eerst Auto Hedge aan" : ""}</span>
          </label>
          {enabled && <>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 12 }}>
              <label style={{ fontSize: 12 }}>Afbouwen over totale daling (%)
                <input aria-label="Totale daling voor afbouw" type="text" inputMode="decimal" value={totalPct} onChange={(e) => setTotalPct(e.target.value)} style={field} disabled={saving} />
              </label>
              <label style={{ fontSize: 12 }}>In hoeveel stappen
                <input aria-label="Aantal afbouwstappen" type="number" min="1" max="100" step="1" inputMode="numeric" value={steps} onChange={(e) => setSteps(e.target.value)} style={field} disabled={saving} />
              </label>
            </div>
            {check.ok
              ? <p style={{ marginTop: 10, fontSize: 13 }}>Elke <b>{fmt(check.stepPct, 4)}% daling</b> verkoopt de bot <b>{fmt(check.sellPct, 4)}% van de SHORT</b> · leeg bij <b>−{fmt(check.totalPct, 4)}%</b>, daarna weer 100% hedgen</p>
              : <p role="alert" style={{ color: "#ff8f8f", fontSize: 13 }}>{check.message}</p>}
          </>}
          {enabled && <p style={{ fontSize: 11, opacity: .75 }}>Stap te klein voor Aster? Dan sluit de bot de SHORT 100% en zet 90% van de LONG terug.</p>}
          {error && <p role="alert" style={{ color: "#ff8f8f", fontSize: 12 }}>{error}</p>}
          {message && <p style={{ color: "#9fe0a8", fontSize: 12 }}>{message}</p>}
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button type="button" style={button} onClick={() => void save()} disabled={saving || !dirty || (enabled && !check.ok)}>{saving ? "Opslaan…" : "Opslaan"}</button>
            <button type="button" style={button} onClick={() => setFlipped(true)}>Draai kaart ↻</button>
          </div>
        </div>
        <div style={{ ...card, position: "absolute", inset: 0, transform: "rotateY(180deg)", minHeight: 300 }}>
          <strong style={{ color: GOLD }}>AFBOUWCYCLUS · VOORBEELD VANAF $100</strong>
          <div style={{ overflowY: "auto", maxHeight: 120, marginTop: 8, fontSize: 12 }}>
            {ladder.map((x) => <div key={x.step} style={{ padding: "4px 0", borderBottom: "1px solid #354438" }}>
              Stap {x.step}: ${fmt(x.price, 4)} (−{fmt(x.dropPct, 4)}%) · SHORT {fmt(x.remainingPct)}% over
            </div>)}
          </div>
          <p style={{ fontSize: 12, opacity: .85, marginTop: 10 }}>
            In het Tradecentrum en bij de gehedgede posities krijgt een munt die wordt afgebouwd het label <b>UNWIND stap/totaal · % gedekt</b>{live ? "" : " (met TEST zolang er geen echte orders gaan)"}.
          </p>
          <button type="button" style={{ ...button, marginTop: 10 }} onClick={() => setFlipped(false)}>↶ Instellingen</button>
        </div>
      </div>
    </div>
  </section>;
}
