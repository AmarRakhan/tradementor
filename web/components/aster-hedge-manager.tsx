"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import styles from "./aster-hedge-manager.module.css";

const REFERENCE = "file_00000000032881f495cdc99757a7d126";

type HedgeStatus = "below_target" | "within_target" | "above_target" | "unavailable";
type HedgeAction = "OPEN_SHORT" | "OPEN_LONG" | "CLOSE_SHORT" | "CLOSE_LONG";
type View = "overview" | "settings" | "recovery" | "confirm" | "progress";

type Settings = {
  targetPercent: number;
  healthyMinPercent: number;
  healthyMaxPercent: number;
  maxCorrectionPercent: number;
};

type Exposure = {
  reliable: boolean;
  longExposureUsd: number;
  shortExposureUsd: number;
  netExposureUsd: number;
  netSide: "LONG" | "SHORT" | "FLAT";
  hedgeCoveragePercent: number | null;
  status: HedgeStatus;
  openPositionCount: number;
  longPositionCount: number;
  shortPositionCount: number;
};

type MarginEvidence = { marginUsd: number; source: string; sampleCount: number };
type HedgeState = {
  reliable: boolean;
  settings: Settings;
  exposure: Exposure;
  averageStartMargin: { LONG: MarginEvidence; SHORT: MarginEvidence };
  actions: { recommended: HedgeAction | null; alternative: HedgeAction | null };
  generatedAt: string;
};

type PlanItem = {
  index: number;
  symbol: string;
  side: "LONG" | "SHORT";
  quantity: number;
  plannedNotionalUsd: number;
  leverage: number;
  plannedMarginUsd: number;
  unrealizedPnlUsd?: number;
};

type HedgePreview = {
  reliable: boolean;
  previewId: string;
  action: HedgeAction;
  seatCount: number;
  marginPerSeatUsd: number;
  marginSource: string;
  totalMarginUsd: number;
  plannedNotionalUsd: number;
  maximumSeatsByMargin: number;
  before: Exposure;
  after: Exposure;
  settings: Settings;
  stepTargetPercent: number | null;
  items: PlanItem[];
  expiresAt: string;
};

type RecoveryStatus = {
  actionId: string;
  status: "ACTIVE" | "COMPLETED" | "STOPPED" | "FAILED" | "BLOCKED";
  action: HedgeAction;
  seatCount: number;
  completedCount: number;
  activeCount: number;
  remainingCount: number;
  before: Exposure;
  current: Exposure;
  expectedAfter: Exposure;
  results?: Array<{ index: number; symbol: string; side: string; status: string; notionalUsd?: number }>;
  error?: string;
};

function money(value: number | null | undefined, decimals = 2) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `US$ ${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(Math.abs(value))}`;
}
function percent(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: Number.isInteger(value) ? 0 : 1, maximumFractionDigits: 1 }).format(value)}%`;
}
function signedMoney(value: number) {
  return `${value > 0 ? "+" : value < 0 ? "-" : ""}${money(value, 0)}`;
}
function statusLabel(status: HedgeStatus) {
  if (status === "below_target") return "Onder doel";
  if (status === "above_target") return "Boven doel";
  if (status === "within_target") return "Binnen doel";
  return "Niet beschikbaar";
}
function actionLabel(action: HedgeAction | null) {
  if (action === "OPEN_SHORT") return "SHORTS openen";
  if (action === "OPEN_LONG") return "LONGS openen";
  if (action === "CLOSE_SHORT") return "SHORTS sluiten";
  if (action === "CLOSE_LONG") return "LONGS sluiten";
  return "Geen actie";
}
function actionVerb(action: HedgeAction | null, count: number) {
  if (!action) return "Geen actie nodig";
  const side = action.endsWith("SHORT") ? "SHORT" : "LONG";
  return `${action.startsWith("OPEN") ? "Open" : "Sluit"} ${count} ${side}-stoel${count === 1 ? "" : "en"}`;
}
function actionSide(action: HedgeAction) { return action.endsWith("SHORT") ? "SHORT" : "LONG"; }
function isOpenAction(action: HedgeAction) { return action.startsWith("OPEN"); }

function Ring({ exposure, target }: { exposure: Exposure; target: number }) {
  const coverage = exposure.hedgeCoveragePercent ?? 0;
  const angle = Math.min(360, Math.max(0, coverage * 3.6));
  return <div className={`${styles.ring} ${styles[exposure.status]}`} style={{ "--hm-angle": `${angle}deg` } as CSSProperties}>
    <div><strong>{percent(exposure.hedgeCoveragePercent)}</strong><small>Doel {percent(target)}</small><b>{statusLabel(exposure.status)}</b></div>
  </div>;
}

function Stepper({ label, value, onChange, min, max, step = 1 }: { label: string; value: number; onChange: (value: number) => void; min: number; max: number; step?: number }) {
  const next = (delta: number) => onChange(Math.min(max, Math.max(min, Math.round((value + delta) * 100) / 100)));
  return <div className={styles.settingRow}><span>{label}</span><div><button type="button" onClick={() => next(-step)}>−</button><strong>{percent(value)}</strong><button type="button" onClick={() => next(step)}>+</button></div></div>;
}

export function AsterHedgeManager({ onClose }: { onClose: () => void }) {
  const [view, setView] = useState<View>("overview");
  const [state, setState] = useState<HedgeState | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [action, setAction] = useState<HedgeAction | null>(null);
  const [seatCount, setSeatCount] = useState(10);
  const [preview, setPreview] = useState<HedgePreview | null>(null);
  const [recovery, setRecovery] = useState<RecoveryStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const previewRequest = useRef(0);
  const stepping = useRef(false);

  const loadState = useCallback(async () => {
    const next = await authenticatedRequest("/api/exchanges/aster/hedge-recovery/state", { cache: "no-store" }) as HedgeState;
    setState(next);
    setDraft(next.settings);
    setAction((current) => current || next.actions.recommended);
    return next;
  }, []);

  useEffect(() => {
    let alive = true;
    const boot = async () => {
      try {
        await loadState();
        const active = await authenticatedRequest("/api/exchanges/aster/hedge-recovery/active", { cache: "no-store" }) as ({ active: boolean } & Partial<RecoveryStatus>);
        if (alive && active.active && active.actionId) {
          setRecovery(active as RecoveryStatus);
          setView("progress");
        }
      } catch (error) {
        if (alive) setMessage(error instanceof Error ? error.message : "Hedgegegevens konden niet worden geladen.");
      }
    };
    void boot();
    return () => { alive = false; };
  }, [loadState]);

  useEffect(() => {
    if (view !== "recovery" || !action || !state || state.exposure.status === "within_target") return;
    const requestId = ++previewRequest.current;
    const timer = window.setTimeout(async () => {
      try {
        setMessage("");
        const next = await authenticatedRequest("/api/exchanges/aster/hedge-recovery/preview", {
          method: "POST", body: JSON.stringify({ action, seat_count: seatCount }),
        }) as HedgePreview;
        if (requestId === previewRequest.current) setPreview(next);
      } catch (error) {
        if (requestId === previewRequest.current) {
          setPreview(null);
          setMessage(error instanceof Error ? error.message : "De herstelpreview kon niet veilig worden berekend.");
        }
      }
    }, 220);
    return () => window.clearTimeout(timer);
  }, [view, action, seatCount, state]);

  const saveSettings = async () => {
    if (!draft || busy) return;
    setBusy(true); setMessage("");
    try {
      const next = await authenticatedRequest("/api/exchanges/aster/hedge-recovery/settings", { method: "PUT", body: JSON.stringify({
        target_percent: draft.targetPercent,
        healthy_min_percent: draft.healthyMinPercent,
        healthy_max_percent: draft.healthyMaxPercent,
        max_correction_percent: draft.maxCorrectionPercent,
      }) }) as HedgeState;
      setState(next); setDraft(next.settings); setAction(next.actions.recommended); setView("overview");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Instellingen konden niet worden opgeslagen."); }
    finally { setBusy(false); }
  };

  const startRecovery = async () => {
    if (!preview || busy) return;
    setBusy(true); setMessage("");
    try {
      const started = await authenticatedRequest("/api/exchanges/aster/hedge-recovery/start", {
        method: "POST", body: JSON.stringify({
          preview_id: preview.previewId, confirm: true,
          idempotency_key: `hedge-recovery-${Date.now()}-${crypto.randomUUID()}`,
        }),
      }) as RecoveryStatus;
      setRecovery(started); setView("progress");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Hedge-herstel kon niet veilig worden gestart."); }
    finally { setBusy(false); }
  };

  const refreshRecovery = useCallback(async (actionId: string) => {
    const next = await authenticatedRequest(`/api/exchanges/aster/hedge-recovery/${encodeURIComponent(actionId)}`, { cache: "no-store" }) as RecoveryStatus;
    setRecovery(next);
    return next;
  }, []);

  useEffect(() => {
    if (view !== "progress" || !recovery?.actionId || recovery.status !== "ACTIVE") return;
    let cancelled = false;
    const run = async () => {
      if (stepping.current || cancelled) return;
      stepping.current = true;
      try {
        const current = await refreshRecovery(recovery.actionId);
        if (cancelled || current.status !== "ACTIVE") return;
        await authenticatedRequest(`/api/exchanges/aster/hedge-recovery/${encodeURIComponent(recovery.actionId)}/step`, { method: "POST", body: JSON.stringify({ confirm: true }) });
        if (!cancelled) {
          const after = await refreshRecovery(recovery.actionId);
          if (after.status === "COMPLETED") void loadState();
        }
      } catch (error) {
        if (!cancelled) setMessage(error instanceof Error ? error.message : "Een herstelstap is veilig gestopt.");
      } finally {
        stepping.current = false;
        if (!cancelled) window.setTimeout(run, 550);
      }
    };
    const timer = window.setTimeout(run, 120);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [view, recovery?.actionId, recovery?.status, refreshRecovery, loadState]);

  const stopRecovery = async () => {
    if (!recovery?.actionId || busy) return;
    setBusy(true);
    try {
      const next = await authenticatedRequest(`/api/exchanges/aster/hedge-recovery/${encodeURIComponent(recovery.actionId)}/stop`, { method: "POST", body: JSON.stringify({ confirm: true }) }) as RecoveryStatus;
      setRecovery(next); await loadState();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Stoppen kon niet veilig worden bevestigd."); }
    finally { setBusy(false); }
  };

  const beginRecovery = () => {
    if (!state?.actions.recommended) return;
    setAction(state.actions.recommended); setPreview(null); setSeatCount(10); setView("recovery");
  };

  const title = view === "settings" ? "Hedge instellingen" : view === "recovery" ? "Hedge herstellen" : view === "confirm" ? "Bevestig actie" : view === "progress" ? "Hedge herstel actief" : "Hedge Dekking";
  const exposure = state?.exposure;
  const config = state?.settings;
  const margin = action && state ? state.averageStartMargin[actionSide(action)] : null;
  const progressExposure = recovery?.current || recovery?.before;
  const quickSeats = [5, 10, 20, 30, 50];

  return <div className={styles.backdrop} data-reference={REFERENCE} role="presentation">
    <section className={styles.shell} role="dialog" aria-modal="true" aria-label={title}>
      <header className={styles.header}>
        <button type="button" className={styles.back} onClick={() => view === "overview" ? onClose() : setView(view === "confirm" ? "recovery" : "overview")} aria-label="Terug">‹</button>
        <h2>{title}</h2>
        <button type="button" className={styles.close} onClick={onClose} aria-label="Sluiten">×</button>
      </header>

      {view === "overview" && exposure && config ? <>
        <div className={styles.tabs}><button className={styles.activeTab}>Overzicht</button><button onClick={() => setView("settings")}>Instellingen</button></div>
        <div className={styles.center}><Ring exposure={exposure} target={config.targetPercent} /></div>
        <p className={styles.summary}>{exposure.status === "within_target" ? "Je hedge ligt binnen je doelzone. Geen actie nodig." : exposure.status === "below_target" ? "Je hedge ligt onder je doelzone. Je portefeuille is te zwaar LONG." : exposure.status === "above_target" ? "Je hedge ligt boven je doelzone. Je portefeuille is te zwaar SHORT." : "De hedge kan nu niet betrouwbaar worden berekend."}</p>
        <div className={styles.metrics}>
          <article><small>LONG EXPOSURE</small><strong>{money(exposure.longExposureUsd, 0)}</strong><b>LONG</b></article>
          <article className={styles.short}><small>SHORT EXPOSURE</small><strong>{money(exposure.shortExposureUsd, 0)}</strong><b>SHORT</b></article>
          <article><small>NETTO OPEN</small><strong>{signedMoney(exposure.netExposureUsd)}</strong><b>{exposure.netSide}</b></article>
        </div>
        <div className={styles.detailList}>
          <p><span>Actieve posities</span><strong>{exposure.openPositionCount}</strong></p>
          <p><span>Long posities</span><strong>{exposure.longPositionCount}</strong></p>
          <p><span>Short posities</span><strong>{exposure.shortPositionCount}</strong></p>
          <p><span>Gem. long startmargin</span><strong>{money(state.averageStartMargin.LONG.marginUsd)}</strong></p>
          <p><span>Gem. short startmargin</span><strong>{money(state.averageStartMargin.SHORT.marginUsd)}</strong></p>
        </div>
        <div className={`${styles.statusBox} ${styles[exposure.status]}`}><b>{statusLabel(exposure.status)}</b><span>Doel {percent(config.targetPercent)} · zone {percent(config.healthyMinPercent)} – {percent(config.healthyMaxPercent)}</span></div>
        {exposure.status !== "within_target" && state.actions.recommended ? <button type="button" className={styles.primary} onClick={beginRecovery}>Start hedge-herstel →</button> : null}
        <button type="button" className={styles.secondary} onClick={() => setView("settings")}>Hedge-instellingen wijzigen</button>
      </> : null}

      {view === "settings" && draft ? <>
        <div className={styles.panel}><h3>Hedge doel & zone</h3>
          <Stepper label="Hedge doel" value={draft.targetPercent} onChange={(v) => setDraft({ ...draft, targetPercent: v })} min={1} max={200} />
          <Stepper label="Ondergrens doelzone" value={draft.healthyMinPercent} onChange={(v) => setDraft({ ...draft, healthyMinPercent: v })} min={0} max={200} />
          <Stepper label="Bovengrens doelzone" value={draft.healthyMaxPercent} onChange={(v) => setDraft({ ...draft, healthyMaxPercent: v })} min={1} max={250} />
        </div>
        <div className={styles.info}>ⓘ De bot geeft een actie wanneer je hedge dekking buiten deze zone valt.</div>
        <div className={styles.panel}><h3>Herstelplan instellingen</h3>
          <Stepper label="Max. correctie per stap" value={draft.maxCorrectionPercent} onChange={(v) => setDraft({ ...draft, maxCorrectionPercent: v })} min={1} max={100} />
          <div className={styles.toggleRow}><span><b>Gebruik gemiddelde margin</b><small>Gemiddelde oorspronkelijke startmargin van bestaande posities, per zijde.</small></span><i>✓</i></div>
          {state ? <div className={styles.marginGrid}><span>Gem. LONG startmargin <b>{money(state.averageStartMargin.LONG.marginUsd)}</b></span><span>Gem. SHORT startmargin <b>{money(state.averageStartMargin.SHORT.marginUsd)}</b></span></div> : null}
        </div>
        <div className={styles.tip}>💡 Een kleinere correctiestap verdeelt het herstel over meerdere actuele herberekeningen.</div>
        <button type="button" className={styles.primary} onClick={saveSettings} disabled={busy}>{busy ? "Opslaan…" : "Opslaan"}</button>
      </> : null}

      {view === "recovery" && state && config && exposure && state.actions.recommended ? <>
        <div className={styles.situation}><span>Hedge dekking<strong>{percent(exposure.hedgeCoveragePercent)}</strong></span><span>Doel<strong>{percent(config.targetPercent)}</strong></span><span>Netto open<strong>{signedMoney(exposure.netExposureUsd)}</strong><small>{exposure.netSide}</small></span></div>
        <div className={`${styles.warning} ${styles[exposure.status]}`}><b>{exposure.status === "below_target" ? "Hedge te laag" : "Hedge te hoog"}</b><span>{exposure.status === "below_target" ? "Je portefeuille is te zwaar LONG. Verhoog je bescherming." : "Je portefeuille is te zwaar SHORT. Breng je verhouding terug richting doel."}</span></div>
        <h3 className={styles.stepTitle}>1. Kies herstelmethode</h3>
        <div className={styles.actionChoices}>
          {[state.actions.recommended, state.actions.alternative].filter(Boolean).map((item, index) => <button key={item} type="button" className={action === item ? styles.selected : ""} onClick={() => { setAction(item as HedgeAction); setPreview(null); }}><b>{actionLabel(item)}</b><small>{index === 0 ? "(aanbevolen)" : "(alternatief)"}</small></button>)}
        </div>
        <h3 className={styles.stepTitle}>2. Aantal stoelen kiezen</h3>
        <div className={styles.seatStepper}><button type="button" onClick={() => setSeatCount(Math.max(1, seatCount - 1))}>−</button><strong>{seatCount}</strong><button type="button" onClick={() => setSeatCount(Math.min(100, seatCount + 1))}>+</button></div>
        <div className={styles.quickSeats}>{quickSeats.map((count) => <button key={count} type="button" className={seatCount === count ? styles.selectedQuick : ""} onClick={() => setSeatCount(count)}>{count}</button>)}</div>
        <h3 className={styles.stepTitle}>3. Gebruikte gemiddelde margin</h3>
        <div className={styles.panel}><div className={styles.marginEvidence}><span>Gemiddelde {actionSide(action!)} startmargin<small>{margin?.source === "same_side_original_average" ? `uit ${margin.sampleCount} bewezen startposities` : "veilige botconfig-fallback"}</small></span><strong>{money(margin?.marginUsd)}</strong></div><div className={styles.marginEvidence}><span>Geschatte totale margin</span><strong>{preview ? money(preview.totalMarginUsd) : "berekenen…"}</strong></div></div>
        {preview ? <div className={styles.impact}><h3>▥ Verwachte impact <small>live berekening</small></h3><p><span>Huidige hedge</span><strong>{percent(preview.before.hedgeCoveragePercent)}</strong></p><p><span>Verwachte hedge na fills</span><strong>{percent(preview.after.hedgeCoveragePercent)}</strong></p><p><span>Geplande exposure</span><strong>{money(preview.plannedNotionalUsd, 0)}</strong></p><p><span>Stapdoel</span><strong>{percent(preview.stepTargetPercent)}</strong></p></div> : null}
        {preview && seatCount > preview.maximumSeatsByMargin ? <div className={styles.error}>Onvoldoende beschikbare margin. Maximaal mogelijk: {preview.maximumSeatsByMargin} stoelen.</div> : null}
        <button type="button" className={styles.primary} disabled={!preview || seatCount > (preview?.maximumSeatsByMargin ?? 0)} onClick={() => setView("confirm")}>{actionVerb(action, seatCount)}</button>
      </> : null}

      {view === "confirm" && preview ? <>
        <div className={styles.rocket}>↗</div><h3 className={styles.confirmTitle}>{actionVerb(preview.action, preview.seatCount)}</h3>
        <p className={styles.confirmCopy}>Je staat op het punt deze hedge-herstelactie uit te voeren. Preview en uitvoering gebruiken hetzelfde orderplan.</p>
        <div className={styles.confirmGrid}>
          <p><span>Aantal posities</span><strong>{preview.seatCount} {actionSide(preview.action)}</strong></p>
          <p><span>Margin per positie</span><strong>{money(preview.marginPerSeatUsd)}</strong></p>
          <p><span>Totale margin</span><strong>{money(preview.totalMarginUsd)}</strong></p>
          <p><span>Geplande exposure</span><strong>{money(preview.plannedNotionalUsd, 0)}</strong></p>
          <p><span>Huidige hedge</span><strong>{percent(preview.before.hedgeCoveragePercent)}</strong></p>
          <p><span>Verwacht na fills</span><strong>{percent(preview.after.hedgeCoveragePercent)}</strong></p>
        </div>
        {!isOpenAction(preview.action) ? <div className={styles.candidates}><h4>Te sluiten posities</h4>{preview.items.map((item) => <p key={`${item.symbol}-${item.side}`}><b>{item.symbol}</b><span>{item.side} · {money(item.plannedNotionalUsd, 0)} · P&amp;L {item.unrealizedPnlUsd !== undefined ? signedMoney(item.unrealizedPnlUsd) : "—"}</span></p>)}</div> : <div className={styles.info}>ⓘ Nieuwe stoelen gebruiken de gemiddelde startmargin van de betreffende zijde. Leverage en orderprecision worden per markt gevalideerd.</div>}
        <button type="button" className={styles.primary} onClick={startRecovery} disabled={busy}>{busy ? "Starten…" : "🚀 Ja, start hedge-herstel"}</button>
        <button type="button" className={styles.secondary} onClick={() => setView("recovery")} disabled={busy}>Annuleren</button>
      </> : null}

      {view === "progress" && recovery && progressExposure ? <>
        <div className={styles.center}><Ring exposure={progressExposure} target={state?.settings.targetPercent ?? preview?.settings.targetPercent ?? 80} /></div>
        <p className={styles.progressState}>{recovery.status === "ACTIVE" ? "Bezig met uitvoeren…" : recovery.status === "COMPLETED" ? "Herstelstap voltooid ✓" : recovery.status === "STOPPED" ? "Herstel gestopt" : "Herstel vereist aandacht"}</p>
        <div className={styles.progressPanel}><h3>Voortgang — huidige stap</h3><strong>{recovery.completedCount} / {recovery.seatCount} uitgevoerd</strong><div className={styles.progressBar}><i style={{ width: `${Math.min(100, recovery.seatCount ? recovery.completedCount / recovery.seatCount * 100 : 0)}%` }} /></div><p><span>✓ Posities uitgevoerd</span><b>{recovery.completedCount}</b></p><p><span>◌ Nog te verwerken</span><b>{recovery.remainingCount}</b></p></div>
        <div className={styles.confirmGrid}><p><span>Start hedge</span><strong>{percent(recovery.before.hedgeCoveragePercent)}</strong></p><p><span>Huidige hedge (live)</span><strong>{percent(recovery.current.hedgeCoveragePercent)}</strong></p><p><span>Verwacht na alle fills</span><strong>{percent(recovery.expectedAfter.hedgeCoveragePercent)}</strong></p></div>
        {recovery.error ? <div className={styles.error}>{recovery.error}</div> : null}
        {recovery.status === "ACTIVE" ? <button type="button" className={styles.stop} onClick={stopRecovery} disabled={busy}>⏹ Stoppen</button> : <button type="button" className={styles.primary} onClick={async () => { await loadState(); setView("overview"); }}>Terug naar overzicht</button>}
      </> : null}

      {message ? <div className={styles.error}>{message}</div> : null}
    </section>
  </div>;
}
