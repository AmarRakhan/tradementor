"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { WEBAPP_BUILD_NUMBER } from "@/lib/app-version";
import { recoveryLadder, validateRecoverySettings } from "@/lib/short-recovery.mjs";

// Hedge afbouwen settings in the Auto Hedge screen, between the loss thresholds and "Gehedgede posities".
// Build 623: one card per side with its own settings. hedgeSide "SHORT" = SHORT-hedge of a LONG position,
// reduced while the price falls; hedgeSide "LONG" = LONG-hedge of a SHORT position, reduced while it rises.
// Saving only stores settings; the server worker decides and places every order through the Auto Hedge engine.

type Plan = { enabled: boolean; steps: number; totalPct: string; stepPct?: string; rebuySteps?: number; safetyNetPct?: string; rehedgePct?: string };
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
  // Build 634 (grid): buy back after N levels up, and the vangnet beyond the last level.
  const [rebuy, setRebuy] = useState(String(plan.rebuySteps ?? 1));
  const [safety, setSafety] = useState(String(plan.safetyNetPct ?? plan.totalPct));
  // Build 646: "Terughedgen" X% (standaard 100) voor terugkopen en vangnet; 0 = na volledige afbouw niets meer.
  const [rehedge, setRehedge] = useState(String(plan.rehedgePct ?? "100"));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    setEnabled(plan.enabled); setSteps(String(plan.steps)); setTotalPct(String(plan.totalPct));
    setRebuy(String(plan.rebuySteps ?? 1)); setSafety(String(plan.safetyNetPct ?? plan.totalPct));
    setRehedge(String(plan.rehedgePct ?? "100"));
  }, [plan.enabled, plan.steps, plan.totalPct, plan.rebuySteps, plan.safetyNetPct, plan.rehedgePct]);

  const check = validateRecoverySettings(steps, totalPct, hedgeSide);
  const ladder = useMemo(() => recoveryLadder(steps, totalPct, 100, hedgeSide), [steps, totalPct, hedgeSide]);
  const rebuyN = Number(rebuy);
  const safetyN = Number(String(safety).replace(",", "."));
  const rehedgeN = Number(String(rehedge).replace(",", "."));
  const gridOk = Number.isInteger(rebuyN) && rebuyN >= 0 && rebuyN <= 100 && Number.isFinite(safetyN) && safetyN > 0 && safetyN < 100
    && Number.isFinite(rehedgeN) && rehedgeN >= 0 && rehedgeN <= 100;
  const dirty = enabled !== plan.enabled || steps !== String(plan.steps) || totalPct !== String(plan.totalPct)
    || rebuy !== String(plan.rebuySteps ?? 1) || safety !== String(plan.safetyNetPct ?? plan.totalPct)
    || rehedge !== String(plan.rehedgePct ?? "100");

  async function save(nextEnabled = enabled) {
    if (nextEnabled && !check.ok) { setError(check.message); return; }
    if (nextEnabled && !gridOk) { setError("Terugkopen: 0 (uit) t/m 100 stappen. Terughedgen: 0% t/m 100%. Vangnet: tussen 0% en 100%."); return; }
    // Switching OFF always works, even with half-typed inputs: keep the last saved values.
    const payload = check.ok
      ? { enabled: nextEnabled, steps: check.steps, totalPct: String(check.totalPct),
          ...(gridOk ? { rebuySteps: rebuyN, safetyNetPct: String(safetyN), rehedgePct: String(rehedgeN) } : {}) }
      : { enabled: false, steps: plan.steps, totalPct: String(plan.totalPct) };
    setSaving(true); setError(""); setMessage("");
    try {
      const next = await authenticatedRequest("/api/exchanges/aster/position-loss-auto-hedge/short-recovery", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload, hedgeSide, clientBuild: String(WEBAPP_BUILD_NUMBER) }),
      }) as AutoHedgeLike;
      onSaved(next);
      setMessage(nextEnabled ? "Opgeslagen · geldt direct voor alle lopende posities aan deze kant." : `${hedgeSide}-hedge afbouwen staat UIT · posities blijven 100% gehedged.`);
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
        <div className="plah-exact-box"><small>Terugkopen na stappen {up ? "daling" : "stijging"} (0 = uit)</small>
          <label><b>#</b><input aria-label={`Terugkopen na aantal stappen (${hedgeSide}-hedge)`} type="number" min="0" max="100" step="1" inputMode="numeric" value={rebuy} onChange={(e) => setRebuy(e.target.value)} disabled={saving} /></label>
        </div>
        <div className="plah-exact-box"><small>Terughedgen (terugkopen + vangnet)</small>
          <label><b>%</b><input aria-label={`Terughedgen in procent (${hedgeSide}-hedge)`} type="text" inputMode="decimal" value={rehedge} onChange={(e) => setRehedge(e.target.value)} disabled={saving} /></label>
        </div>
        <div className="plah-exact-box"><small>Vangnet na extra {move}</small>
          <label><b>%</b><input aria-label={`Vangnet in procent (${hedgeSide}-hedge)`} type="text" inputMode="decimal" value={safety} onChange={(e) => setSafety(e.target.value)} disabled={saving} /></label>
        </div>
      </div>
      {gridOk && rehedgeN < 100 && <p className="plah-info plah-unwind-error" role="note"><span>!</span>
        {rehedgeN === 0
          ? <>Terughedgen 0%: na volledige afbouw heeft je {protectedSide} geen bescherming meer. Geen vangnet en geen nieuwe Auto Hedge op die munt; de {protectedSide} moet het zelf redden via TP of Portfolio TP.</>
          : <>Terughedgen {fmt(rehedgeN, 2)}%: bij terugkopen zet de bot maar {fmt(rehedgeN, 2)}% van het verkochte deel terug en het vangnet hedget {fmt(rehedgeN, 2)}% van je {protectedSide}. Je netto {protectedSide} groeit zo met elke schommeling; bij een harde daling ben je minder beschermd.</>}
        {" "}Zet je dit later weer hoger, dan gaat de grid verder waar hij staat en wordt er niet meteen opnieuw gehedged.
      </p>}
      {check.ok ? <>
        <div className="plah-threshold-value plah-unwind-value">elke {fmt(check.stepPct, 4)}% · {fmt(check.sellPct, 4)}%</div>
        <p className="plah-info"><span>i</span>
          Vanaf de instapkoers van de hedge verkoopt de bot bij elke {fmt(check.stepPct, 4)}% {move} {fmt(check.sellPct, 4)}% van de {hedgeSide}
          (eerste stap {sign}{fmt(ladder[0]?.dropPct ?? 0, 4)}%, leeg bij {sign}{fmt(check.totalPct, 4)}%). Alleen met winst na fees.{" "}
          {gridOk && rebuyN === 0
            ? <>Terugkopen staat uit: wat verkocht is blijft verkocht, ook als de koers terugkomt.</>
            : <>Grid: komt de koers {gridOk ? rebuyN : 1} stap{gridOk && rebuyN === 1 ? "" : "pen"} terug, dan koopt de bot {gridOk && rehedgeN < 100 ? `${fmt(rehedgeN, 2)}% van ` : ""}dat deel van de {hedgeSide} weer terug; zo groeit je netto {protectedSide} hoe verder de koers {up ? "stijgt" : "daalt"} en pak je bij elke schommeling een stap winst.</>}{" "}
          {gridOk && rehedgeN === 0
            ? <>Alles afgebouwd: klaar voor die munt, er wordt niet opnieuw gehedged.</>
            : <>Alles afgebouwd en nog {gridOk ? fmt(safetyN, 4) : "…"}% verder: vangnet, weer {gridOk ? fmt(rehedgeN, 2) : "100"}% hedgen en een nieuw grid vanaf daar.</>}{" "}
          Kleine munt: minder, grotere stappen (elke order minstens het Aster-minimum). Een wijziging geldt direct voor alle lopende posities.
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
