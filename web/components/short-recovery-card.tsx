"use client";

import { useEffect, useState, type ReactNode } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { WEBAPP_BUILD_NUMBER } from "@/lib/app-version";
import { validateRecoverySettings } from "@/lib/short-recovery.mjs";
import { HedgePreview, type PreviewSettings } from "@/components/hedge-preview";
import { DrawdownReference, useEntryDrawdown } from "@/components/entry-drawdown";

// Hedge afbouwen settings in the Auto Hedge screen, between the loss thresholds and "Gehedgede posities".
// Build 623: one card per side with its own settings. hedgeSide "SHORT" = SHORT-hedge of a LONG position,
// reduced while the price falls; hedgeSide "LONG" = LONG-hedge of a SHORT position, reduced while it rises.
// Saving only stores settings; the server worker decides and places every order through the Auto Hedge engine.

type Plan = { enabled: boolean; steps: number; totalPct: string; stepPct?: string; rebuySteps?: number; safetyNetPct?: string; rehedgePct?: string; distribution?: Distribution };
type HedgeSide = "SHORT" | "LONG";
type Distribution = "EQUAL" | "ASCENDING" | "STEEP";
const DISTRIBUTIONS: { key: Distribution; label: string }[] = [
  { key: "EQUAL", label: "Gelijk" }, { key: "ASCENDING", label: "Oplopend" }, { key: "STEEP", label: "Sterk oplopend" },
];
// Build 647: same weights as the server (short_recovery_ladder.part_weights).
function partWeights(n: number, dist: Distribution): number[] {
  return Array.from({ length: n }, (_, i) => (dist === "ASCENDING" ? i + 1 : dist === "STEEP" ? 2 ** i : 1));
}
type AutoHedgeLike = {
  enabled: boolean;
  shortRecoveryPlan?: Plan;
  longRecoveryPlan?: Plan;
  shortRecoveryExecutionEnabled?: boolean;
};
type ToggleRender = (props: { checked: boolean; disabled?: boolean; onChange: () => void; label: string }) => ReactNode;

const fmt = (n: number, d = 2) => n.toLocaleString("nl-NL", { maximumFractionDigits: d });

export function ShortRecoveryCard({ state, onSaved, renderToggle, hedgeSide = "SHORT", maxHedgePct = 100 }: {
  state: AutoHedgeLike;
  onSaved: (next: AutoHedgeLike) => void;
  renderToggle: ToggleRender;
  hedgeSide?: HedgeSide;
  maxHedgePct?: number;
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
  // Build 647: Verdeling — small parts near the start, big parts far away; buying back small first (keuze B).
  const [dist, setDist] = useState<Distribution>(plan.distribution ?? "EQUAL");
  // Build 652: dezelfde gem. max drawdown als in de Portfolio Snapshot, direct boven de afbouwstappen.
  const drawdown = useEntryDrawdown();
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    setEnabled(plan.enabled); setSteps(String(plan.steps)); setTotalPct(String(plan.totalPct));
    setRebuy(String(plan.rebuySteps ?? 1)); setSafety(String(plan.safetyNetPct ?? plan.totalPct));
    setRehedge(String(plan.rehedgePct ?? "100"));
    setDist(plan.distribution ?? "EQUAL");
  }, [plan.enabled, plan.steps, plan.totalPct, plan.rebuySteps, plan.safetyNetPct, plan.rehedgePct, plan.distribution]);

  const check = validateRecoverySettings(steps, totalPct, hedgeSide);
  const rebuyN = Number(rebuy);
  const safetyN = Number(String(safety).replace(",", "."));
  const rehedgeN = Number(String(rehedge).replace(",", "."));
  const gridOk = Number.isInteger(rebuyN) && rebuyN >= 0 && rebuyN <= 100 && Number.isFinite(safetyN) && safetyN > 0 && safetyN < 100
    && Number.isFinite(rehedgeN) && rehedgeN >= 0 && rehedgeN <= 100;
  const dirty = enabled !== plan.enabled || steps !== String(plan.steps) || totalPct !== String(plan.totalPct)
    || rebuy !== String(plan.rebuySteps ?? 1) || safety !== String(plan.safetyNetPct ?? plan.totalPct)
    || rehedge !== String(plan.rehedgePct ?? "100") || dist !== (plan.distribution ?? "EQUAL");

  async function save(nextEnabled = enabled) {
    if (nextEnabled && !check.ok) { setError(check.message); return; }
    if (nextEnabled && !gridOk) { setError("Terugkopen: 0 (uit) t/m 100 stappen. Terughedgen: 0% t/m 100%. Vangnet: tussen 0% en 100%."); return; }
    // Switching OFF always works, even with half-typed inputs: keep the last saved values.
    const payload = check.ok
      ? { enabled: nextEnabled, steps: check.steps, totalPct: String(check.totalPct),
          ...(gridOk ? { rebuySteps: rebuyN, safetyNetPct: String(safetyN), rehedgePct: String(rehedgeN) } : {}), distribution: dist }
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

    <DrawdownReference data={drawdown} />

    {enabled && <>
      <div className="plah-unwind-fields">
        <div className="plah-exact-box"><small>Afbouwen over totale {move}</small>
          <label><b>%</b><input aria-label={`Totale ${move} voor afbouw (${hedgeSide}-hedge)`} type="text" inputMode="decimal" value={totalPct} onChange={(e) => setTotalPct(e.target.value)} disabled={saving} /></label>
        </div>
        <div className="plah-exact-box"><small>In hoeveel stappen</small>
          <label><b>#</b><input aria-label={`Aantal afbouwstappen (${hedgeSide}-hedge)`} type="number" min="1" max="100" step="1" inputMode="numeric" value={steps} onChange={(e) => setSteps(e.target.value)} disabled={saving} /></label>
        </div>
        <div className="plah-exact-box plah-unwind-dist"><small>Verdeling</small>
          <div className="plah-seg" role="radiogroup" aria-label={`Verdeling van de afbouw (${hedgeSide}-hedge)`}>
            {DISTRIBUTIONS.map((d) => <button key={d.key} type="button" role="radio" aria-checked={dist === d.key}
              className={dist === d.key ? "on" : ""} onClick={() => setDist(d.key)} disabled={saving}>{d.label}</button>)}
          </div>
        </div>
        <div className="plah-exact-box"><small>Terugkopen na stappen {up ? "daling" : "stijging"} (0 = uit)</small>
          <label><b>#</b><input aria-label={`Terugkopen na aantal stappen (${hedgeSide}-hedge)`} type="number" min="0" max="100" step="1" inputMode="numeric" value={rebuy} onChange={(e) => setRebuy(e.target.value)} disabled={saving} /></label>
        </div>
        <div className="plah-exact-box"><small>Terughedgen (terugkopen + noodrem)</small>
          <label><b>%</b><input aria-label={`Terughedgen in procent (${hedgeSide}-hedge)`} type="text" inputMode="decimal" value={rehedge} onChange={(e) => setRehedge(e.target.value)} disabled={saving} /></label>
        </div>
        <div className="plah-exact-box"><small>Noodrem: na volledige afbouw nog … {up ? "hoger" : "lager"}</small>
          <label><b>%</b><input aria-label={`Noodrem in procent (${hedgeSide}-hedge)`} type="text" inputMode="decimal" value={safety} onChange={(e) => setSafety(e.target.value)} disabled={saving} /></label>
        </div>
      </div>
      {gridOk && rehedgeN < 100 && <p className="plah-info plah-unwind-error" role="note"><span>!</span>
        {rehedgeN === 0
          ? <>Terughedgen 0%: na volledige afbouw heeft je {protectedSide} geen bescherming meer. Geen noodrem en geen nieuwe Auto Hedge op die munt; de {protectedSide} moet het zelf redden via TP of Portfolio TP.</>
          : <>Terughedgen {fmt(rehedgeN, 2)}%: bij terugkopen zet de bot maar {fmt(rehedgeN, 2)}% van het verkochte deel terug en de noodrem hedget {fmt(rehedgeN, 2)}% van je {protectedSide}. Je netto {protectedSide} groeit zo met elke schommeling; bij een harde daling ben je minder beschermd.</>}
        {" "}Zet je dit later weer hoger, dan gaat de grid verder waar hij staat en wordt er niet meteen opnieuw gehedged.
      </p>}
      {check.ok ? <>
        {(() => {
          const n = check.steps;
          const w = partWeights(n, dist);
          const total = w.reduce((x, y) => x + y, 0);
          const pcts = w.map((x) => (x / total) * 100);
          const maxP = Math.max(...pcts);
          const back = gridOk ? rehedgeN : 100;
          return <>
            <div className="plah-unwind-bars" aria-hidden="true">
              {pcts.map((p, i) => <div key={i} style={{ height: `${Math.max(8, (p / maxP) * 100)}%` }}>
                <em>{fmt(p, 0)}%</em><span>{sign}{fmt(check.stepPct * (i + 1), 2)}%</span>
              </div>)}
            </div>
            <div className="plah-unwind-lines">
              <p><b className="down">OMLAAG</b><span>Elke {fmt(check.stepPct, 4)}% {move} verkoopt de bot een deel van de {hedgeSide}{dist === "EQUAL"
                ? ` (${fmt(pcts[0], 1)}% per stap)` : `: klein eerst (${fmt(pcts[0], 1)}%), groot op het laatst (${fmt(pcts[n - 1], 1)}%)`}. Alleen met winst na fees.</span></p>
              <p><b className="up">OMHOOG</b><span>{gridOk && rebuyN === 0
                ? "Terugkopen staat uit: wat verkocht is blijft verkocht."
                : `Komt de koers ${gridOk ? rebuyN : 1} stap${gridOk && rebuyN === 1 ? "" : "pen"} (${fmt(check.stepPct * (gridOk ? rebuyN : 1), 2)}%) ${up ? "onder" : "boven"} een verkooppunt, dan zet de bot ${fmt(back, 2)}% van een deel terug. Klein eerst, de grote delen pas ${up ? "lager" : "hoger"}.`}</span></p>
              <p><b className="stop">NOODREM</b><span>{gridOk && rehedgeN === 0
                ? "Uit (terughedgen 0%): na volledige afbouw wordt er niet opnieuw gehedged."
                : `Alles afgebouwd en de koers ${up ? "stijgt" : "zakt"} nog ${gridOk ? fmt(safetyN, 4) : "…"}%: in één keer weer ${fmt(back, 2)}% hedgen, nieuwe ronde vanaf daar.`}</span></p>
            </div>
            <p className="plah-info"><span>i</span>Kleine munt: minder, grotere stappen (elke order minstens het Aster-minimum, ook op de laagste stap). Een wijziging geldt direct voor alle lopende posities.</p>
            <HedgePreview hedgeSide={hedgeSide} maxHedgePct={maxHedgePct}
              settings={gridOk ? { steps: n, totalPct: check.totalPct, distribution: dist, rebuySteps: rebuyN, rehedgePct: rehedgeN, safetyNetPct: safetyN } : null}
              onApply={(next: PreviewSettings) => {
                setSteps(String(next.steps)); setTotalPct(String(next.totalPct)); setDist(next.distribution);
                setRebuy(String(next.rebuySteps)); setRehedge(String(next.rehedgePct)); setSafety(String(next.safetyNetPct));
              }} />
          </>;
        })()}
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
