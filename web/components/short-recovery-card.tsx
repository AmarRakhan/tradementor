"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { WEBAPP_BUILD_NUMBER } from "@/lib/app-version";
import { recoveryLadder, validateRecoverySettings } from "@/lib/short-recovery.mjs";

// Hedge afbouwen settings in the Auto Hedge screen, between the loss thresholds and "Gehedgede posities".
// Build 623: one card per side with its own settings. hedgeSide "SHORT" = SHORT-hedge of a LONG position,
// reduced while the price falls; hedgeSide "LONG" = LONG-hedge of a SHORT position, reduced while it rises.
// Saving only stores settings; the server worker decides and places every order through the Auto Hedge engine.

type Plan = { enabled: boolean; steps: number; totalPct: string; stepPct?: string };
type HedgeSide = "SHORT" | "LONG";
type AutoHedgeLike = {
  enabled: boolean;
  shortRecoveryPlan?: Plan;
  longRecoveryPlan?: Plan;
  shortRecoveryExecutionEnabled?: boolean;
};
type ToggleRender = (props: { checked: boolean; disabled?: boolean; onChange: () => void; label: string }) => ReactNode;

const fmt = (n: number, d = 2) => n.toLocaleString("nl-NL", { maximumFractionDigits: d });

export function ShortRecoveryCard({ state, onSaved, renderToggle, hedgeSide = "SHORT" }: {
  state: AutoHedgeLike;
  onSaved: (next: AutoHedgeLike) => void;
  renderToggle: ToggleRender;
  hedgeSide?: HedgeSide;
}) {
  const up = hedgeSide === "LONG";
  const protectedSide = up ? "SHORT" : "LONG";
  const move = up ? "stijging" : "daling";
  const sign = up ? "+" : "−";
  const plan = (up ? state.longRecoveryPlan : state.shortRecoveryPlan) ?? { enabled: false, steps: 4, totalPct: "8" };
  const live = state.shortRecoveryExecutionEnabled === true;
  const [enabled, setEnabled] = useState(plan.enabled);
  const [steps, setSteps] = useState(String(plan.steps));
  const [totalPct, setTotalPct] = useState(String(plan.totalPct));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    setEnabled(plan.enabled); setSteps(String(plan.steps)); setTotalPct(String(plan.totalPct));
  }, [plan.enabled, plan.steps, plan.totalPct]);

  const check = validateRecoverySettings(steps, totalPct, hedgeSide);
  const ladder = useMemo(() => recoveryLadder(steps, totalPct, 100, hedgeSide), [steps, totalPct, hedgeSide]);
  const dirty = enabled !== plan.enabled || steps !== String(plan.steps) || totalPct !== String(plan.totalPct);

  async function save(nextEnabled = enabled) {
    if (nextEnabled && !check.ok) { setError(check.message); return; }
    // Switching OFF always works, even with half-typed inputs: keep the last saved values.
    const payload = check.ok
      ? { enabled: nextEnabled, steps: check.steps, totalPct: String(check.totalPct) }
      : { enabled: false, steps: plan.steps, totalPct: String(plan.totalPct) };
    setSaving(true); setError(""); setMessage("");
    try {
      const next = await authenticatedRequest("/api/exchanges/aster/position-loss-auto-hedge/short-recovery", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload, hedgeSide, clientBuild: String(WEBAPP_BUILD_NUMBER) }),
      }) as AutoHedgeLike;
      onSaved(next);
      setMessage(nextEnabled ? "Opgeslagen · geldt vanaf de volgende afbouwcyclus." : `${hedgeSide}-hedge afbouwen staat UIT · posities blijven 100% gehedged.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Opslaan mislukt");
    } finally {
      setSaving(false);
    }
  }

  function toggle() {
    const next = !enabled;
    setEnabled(next);
    if (!next && plan.enabled) void save(false);   // OFF saves at once; ON first shows the two fields
  }

  return <section className="plah-threshold-card plah-unwind-card" aria-label={`${hedgeSide}-hedge afbouwen`}>
    <div className="plah-threshold-head">
      <div className="plah-unwind-title">
        <label>{hedgeSide}-hedge afbouwen</label>
        <small>Bij een {protectedSide}-positie · bouwt de Auto Hedge-{hedgeSide} in stappen af als de koers verder {up ? "stijgt" : "daalt"}</small>
      </div>
      {renderToggle({ checked: enabled, disabled: saving || (!state.enabled && !enabled), onChange: toggle, label: `${hedgeSide}-hedge afbouwen aan of uit` })}
    </div>

    {!state.enabled && !enabled && <p className="plah-info"><span>i</span> Zet eerst Auto Hedge aan; afbouwen werkt alleen op Auto Hedge-hedges.</p>}

    {enabled && <>
      <div className="plah-unwind-fields">
        <div className="plah-exact-box"><small>Afbouwen over totale {move}</small>
          <label><b>%</b><input aria-label={`Totale ${move} voor afbouw (${hedgeSide}-hedge)`} type="text" inputMode="decimal" value={totalPct} onChange={(e) => setTotalPct(e.target.value)} disabled={saving} /></label>
        </div>
        <div className="plah-exact-box"><small>In hoeveel stappen</small>
          <label><b>#</b><input aria-label={`Aantal afbouwstappen (${hedgeSide}-hedge)`} type="number" min="1" max="100" step="1" inputMode="numeric" value={steps} onChange={(e) => setSteps(e.target.value)} disabled={saving} /></label>
        </div>
      </div>
      {check.ok ? <>
        <div className="plah-threshold-value plah-unwind-value">elke {fmt(check.stepPct, 4)}% · {fmt(check.sellPct, 4)}%</div>
        <p className="plah-info"><span>i</span>
          Vanaf de instapkoers van de hedge verkoopt de bot bij elke {fmt(check.stepPct, 4)}% {move} {fmt(check.sellPct, 4)}% van de {hedgeSide}
          (eerste stap {sign}{fmt(ladder[0]?.dropPct ?? 0, 4)}%, leeg bij {sign}{fmt(check.totalPct, 4)}%). Alleen met winst na fees. Leeg = weer 100% hedgen.
          Stap te klein voor Aster: {hedgeSide} 100% sluiten en 90% van de {protectedSide} terugzetten.
        </p>
      </> : <p className="plah-info plah-unwind-error" role="alert"><span>!</span> {check.message}</p>}
      {!live && <p className="plah-info plah-unwind-test"><span>T</span> TESTMODUS · de bot rekent mee op je echte posities maar plaatst nog geen afbouworders. Gestippelde HEDGED x%-labels zijn testlabels.</p>}
      {dirty && <button type="button" className="plah-unwind-save" onClick={() => void save()} disabled={saving || !check.ok}>
        {saving ? "Opslaan…" : "Opslaan"}
      </button>}
    </>}
    {error && <div className="plah-error" role="alert">{error}</div>}
    {message && <div className="plah-success">{message}</div>}
  </section>;
}
