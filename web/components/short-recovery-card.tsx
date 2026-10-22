"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { WEBAPP_BUILD_NUMBER } from "@/lib/app-version";
import { recoveryLadder, validateRecoverySettings } from "@/lib/short-recovery.mjs";

// SHORT Recovery 2.0 settings block in the Auto Hedge screen, between the loss threshold and
// "Gehedgede posities", in the same style as the threshold card. Saving only stores settings; the
// server worker decides and places every order through the existing Auto Hedge engine.

type Plan = { enabled: boolean; steps: number; totalPct: string; stepPct?: string };
type AutoHedgeLike = {
  enabled: boolean;
  shortRecoveryPlan?: Plan;
  shortRecoveryExecutionEnabled?: boolean;
};
type ToggleRender = (props: { checked: boolean; disabled?: boolean; onChange: () => void; label: string }) => ReactNode;

const fmt = (n: number, d = 2) => n.toLocaleString("nl-NL", { maximumFractionDigits: d });

export function ShortRecoveryCard({ state, onSaved, renderToggle }: {
  state: AutoHedgeLike;
  onSaved: (next: AutoHedgeLike) => void;
  renderToggle: ToggleRender;
}) {
  const plan = state.shortRecoveryPlan ?? { enabled: false, steps: 4, totalPct: "8" };
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

  const check = validateRecoverySettings(steps, totalPct);
  const ladder = useMemo(() => recoveryLadder(steps, totalPct), [steps, totalPct]);
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
        body: JSON.stringify({ ...payload, clientBuild: String(WEBAPP_BUILD_NUMBER) }),
      }) as AutoHedgeLike;
      onSaved(next);
      setMessage(nextEnabled ? "Opgeslagen · geldt vanaf de volgende afbouwcyclus." : "SHORT afbouwen staat UIT · posities blijven 100% gehedged.");
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

  return <section className="plah-threshold-card plah-unwind-card" aria-label="SHORT Recovery 2.0">
    <div className="plah-threshold-head">
      <div className="plah-unwind-title">
        <label>SHORT afbouwen</label>
        <small>Recovery 2.0 · bouwt een Auto Hedge-SHORT in stappen af als de koers verder daalt</small>
      </div>
      {renderToggle({ checked: enabled, disabled: saving || (!state.enabled && !enabled), onChange: toggle, label: "SHORT afbouwen aan of uit" })}
    </div>

    {!state.enabled && !enabled && <p className="plah-info"><span>i</span> Zet eerst Auto Hedge aan; SHORT afbouwen werkt alleen op Auto Hedge-SHORTs.</p>}

    {enabled && <>
      <div className="plah-unwind-fields">
        <div className="plah-exact-box"><small>Afbouwen over totale daling</small>
          <label><b>%</b><input aria-label="Totale daling voor afbouw" type="text" inputMode="decimal" value={totalPct} onChange={(e) => setTotalPct(e.target.value)} disabled={saving} /></label>
        </div>
        <div className="plah-exact-box"><small>In hoeveel stappen</small>
          <label><b>#</b><input aria-label="Aantal afbouwstappen" type="number" min="1" max="100" step="1" inputMode="numeric" value={steps} onChange={(e) => setSteps(e.target.value)} disabled={saving} /></label>
        </div>
      </div>
      {check.ok ? <>
        <div className="plah-threshold-value plah-unwind-value">elke {fmt(check.stepPct, 4)}% · {fmt(check.sellPct, 4)}%</div>
        <p className="plah-info"><span>i</span>
          Vanaf de instapkoers van de hedge verkoopt de bot bij elke {fmt(check.stepPct, 4)}% daling {fmt(check.sellPct, 4)}% van de SHORT
          (eerste stap −{fmt(ladder[0]?.dropPct ?? 0, 4)}%, leeg bij −{fmt(check.totalPct, 4)}%). Leeg = weer 100% hedgen.
          Stap te klein voor Aster: SHORT 100% sluiten en 90% van de LONG terugzetten.
        </p>
      </> : <p className="plah-info plah-unwind-error" role="alert"><span>!</span> {check.message}</p>}
      {!live && <p className="plah-info plah-unwind-test"><span>T</span> TESTMODUS · de bot rekent mee op je echte posities (label UNWIND · TEST) maar plaatst nog geen afbouworders.</p>}
      {dirty && <button type="button" className="plah-unwind-save" onClick={() => void save()} disabled={saving || !check.ok}>
        {saving ? "Opslaan…" : "Opslaan"}
      </button>}
    </>}
    {error && <div className="plah-error" role="alert">{error}</div>}
    {message && <div className="plah-success">{message}</div>}
  </section>;
}
