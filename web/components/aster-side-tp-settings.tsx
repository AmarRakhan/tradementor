"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

type TpMode = "PER_TRADE" | "PORTFOLIO" | "OFF";
type Settings = Record<string, unknown>;
type Cycle = Record<string, unknown>;
type Draft = {
  longDcaDistance: string; shortDcaDistance: string;
  longDcaAmount: string; shortDcaAmount: string;
  maxDcaLong: string; maxDcaShort: string;
  longTp: string; shortTp: string;
  mode: TpMode; portfolioTp: string;
};

const percent = (value: unknown, fallback: number) => {
  const number = Number(value);
  return String((Number.isFinite(number) ? number : fallback) * 100);
};
const numberText = (value: unknown, fallback: number) => {
  const number = Number(value); return String(Number.isFinite(number) ? number : fallback);
};
const parse = (value: string, label: string, allowZero = false) => {
  const number = Number(value.replace(",", "."));
  if (!Number.isFinite(number) || (allowZero ? number < 0 : number <= 0)) throw new Error(`${label} is ongeldig.`);
  return number;
};

function buildDraft(settings: Settings): Draft {
  const legacyDistance = settings.dcaDistance ?? .003;
  const legacyAmount = settings.dcaMarginUsd ?? 2;
  const legacyMax = settings.maxDca ?? 3;
  const legacyTp = settings.takeProfit ?? .015;
  const rawMode = String(settings.takeProfitMode || (settings.takeProfitEnabled === false ? "OFF" : "PER_TRADE")).toUpperCase();
  const mode: TpMode = rawMode === "PORTFOLIO" ? "PORTFOLIO" : rawMode === "OFF" ? "OFF" : "PER_TRADE";
  return {
    longDcaDistance: percent(settings.longDcaDistance ?? legacyDistance, .003),
    shortDcaDistance: percent(settings.shortDcaDistance ?? legacyDistance, .003),
    longDcaAmount: numberText(settings.longDcaMarginUsd ?? settings.longDcaAmount ?? legacyAmount, 2),
    shortDcaAmount: numberText(settings.shortDcaMarginUsd ?? settings.shortDcaAmount ?? legacyAmount, 2),
    maxDcaLong: numberText(settings.maxDcaLong ?? settings.longMaxDca ?? legacyMax, 3),
    maxDcaShort: numberText(settings.maxDcaShort ?? settings.shortMaxDca ?? legacyMax, 3),
    longTp: percent(settings.longTakeProfitValue ?? settings.takeProfitLong ?? legacyTp, .015),
    shortTp: percent(settings.shortTakeProfitValue ?? settings.takeProfitShort ?? legacyTp, .015),
    mode,
    portfolioTp: numberText(settings.portfolioTpPercent, 20),
  };
}

function Field({ label, value, onChange, suffix, disabled = false }: { label: string; value: string; onChange: (value: string) => void; suffix: string; disabled?: boolean }) {
  return <label style={{ display: "grid", gap: 6, opacity: disabled ? .48 : 1 }}><span style={{ fontSize: 12, color: "#b7c2bd", fontWeight: 750 }}>{label}</span><span style={{ display: "flex", alignItems: "center", border: "1px solid #2a3b34", borderRadius: 11, background: "#020706", overflow: "hidden" }}><input disabled={disabled} value={value} inputMode="decimal" onChange={(e) => onChange(e.target.value.replace(",", "."))} style={{ width: "100%", border: 0, outline: 0, background: "transparent", color: "white", padding: "11px 10px", fontSize: 15 }} /><b style={{ paddingRight: 10, color: "#77857f", fontSize: 11 }}>{suffix}</b></span></label>;
}

export function AsterSideTpSettings() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [base, setBase] = useState<Settings>({});
  const [cycle, setCycle] = useState<Cycle>({});
  const [draft, setDraft] = useState<Draft>(() => buildDraft({}));

  const load = useCallback(async () => {
    setBusy(true); setMessage("");
    try {
      const payload = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" }) as Record<string, unknown>;
      const strategy2 = payload.strategy2 && typeof payload.strategy2 === "object" ? payload.strategy2 as Record<string, unknown> : {};
      const settings = strategy2.settings && typeof strategy2.settings === "object" ? strategy2.settings as Settings : {};
      const report = strategy2.multiBbReport && typeof strategy2.multiBbReport === "object" ? strategy2.multiBbReport as Record<string, unknown> : strategy2.report && typeof strategy2.report === "object" ? strategy2.report as Record<string, unknown> : {};
      const cycleValue = report.portfolioCycle && typeof report.portfolioCycle === "object" ? report.portfolioCycle as Cycle : {};
      setBase(settings); setDraft(buildDraft(settings)); setCycle(cycleValue);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Instellingen konden niet worden geladen."); }
    finally { setBusy(false); }
  }, []);

  const launch = useCallback(() => { setOpen(true); void load(); }, [load]);

  useEffect(() => {
    const hidden = new Set<HTMLElement>();
    let button: HTMLButtonElement | null = null;
    const install = () => {
      const maker = document.getElementById("strategy-2-maker");
      const grid = maker?.querySelector(".maker-input.compact-settings-grid") as HTMLElement | null;
      if (!maker || !grid) return;
      for (const label of Array.from(grid.querySelectorAll(":scope > label")) as HTMLElement[]) {
        const text = label.textContent?.trim() || "";
        if (text.startsWith("DCA afstand") || text.startsWith("DCA margin") || text.startsWith("Globale DCA-limiet")) {
          label.style.display = "none"; hidden.add(label);
        }
      }
      const legacyTp = grid.querySelector(":scope > .tp-setting") as HTMLElement | null;
      if (legacyTp) { legacyTp.style.display = "none"; hidden.add(legacyTp); }
      if (!grid.querySelector("[data-side-tp-settings]")) {
        button = document.createElement("button"); button.type = "button"; button.setAttribute("data-side-tp-settings", "true");
        button.textContent = "LONG / SHORT · DCA & TAKE PROFIT INSTELLEN";
        Object.assign(button.style, { minHeight: "52px", borderRadius: "14px", border: "1px solid rgba(88,240,174,.45)", background: "linear-gradient(135deg,rgba(10,55,40,.95),rgba(4,19,15,.98))", color: "#8cf5bd", fontWeight: "900", letterSpacing: ".03em", cursor: "pointer", padding: "12px" });
        button.addEventListener("click", launch);
        const asym = grid.querySelector(":scope > .asym-hedge-card"); grid.insertBefore(button, asym || null);
      }
      const facts = maker.querySelector(".strategy-facts");
      for (const span of Array.from(facts?.querySelectorAll("span") || []) as HTMLElement[]) {
        const text = span.textContent || "";
        if (text.startsWith("DCA globaal") || text.startsWith("TP ")) { span.style.display = "none"; hidden.add(span); }
      }
    };
    install(); const observer = new MutationObserver(install); observer.observe(document.body, { subtree: true, childList: true });
    return () => { observer.disconnect(); button?.remove(); hidden.forEach((node) => { node.style.display = ""; }); };
  }, [launch]);

  const cycleStart = Number(cycle.cycleStartEquity || 0);
  const currentEquity = Number(cycle.currentEquity || 0);
  const selectedPortfolioPct = Number(draft.portfolioTp.replace(",", ".")) || 0;
  const selectedTarget = cycleStart > 0 ? cycleStart * (1 + selectedPortfolioPct / 100) : Number(cycle.targetEquity || 0);
  const warning = draft.mode === "PORTFOLIO" && selectedTarget > 0 && currentEquity >= selectedTarget;
  const distanceUsd = selectedTarget > 0 ? Math.max(0, selectedTarget - currentEquity) : 0;
  const distancePct = currentEquity > 0 ? distanceUsd / currentEquity * 100 : 0;
  const individualActive = draft.mode === "PER_TRADE";

  const summary = useMemo(() => draft.mode === "PORTFOLIO" ? `Portfolio +${draft.portfolioTp}%` : draft.mode === "OFF" ? "Take Profit uit" : `Per trade · L ${draft.longTp}% / S ${draft.shortTp}%`, [draft]);

  async function save() {
    if (busy) return; setBusy(true); setMessage("");
    try {
      const longDistance = parse(draft.longDcaDistance, "DCA-afstand LONG") / 100;
      const shortDistance = parse(draft.shortDcaDistance, "DCA-afstand SHORT") / 100;
      if (longDistance > .50 || shortDistance > .50) throw new Error("DCA-afstand mag maximaal 50% zijn.");
      const maxLong = Math.round(parse(draft.maxDcaLong, "Max DCA LONG", true));
      const maxShort = Math.round(parse(draft.maxDcaShort, "Max DCA SHORT", true));
      if (maxLong > 500 || maxShort > 500) throw new Error("Max DCA mag maximaal 500 zijn.");
      const latest = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" }) as Record<string, unknown>;
      const s2 = latest.strategy2 && typeof latest.strategy2 === "object" ? latest.strategy2 as Record<string, unknown> : {};
      const settings = s2.settings && typeof s2.settings === "object" ? s2.settings as Settings : base;
      const next = {
        ...settings,
        takeProfitMode: draft.mode,
        portfolioTpPercent: parse(draft.portfolioTp, "Portfolio TP"),
        longDcaDistance: longDistance, shortDcaDistance: shortDistance,
        longDcaMarginUsd: parse(draft.longDcaAmount, "DCA-bedrag LONG"), shortDcaMarginUsd: parse(draft.shortDcaAmount, "DCA-bedrag SHORT"),
        longDcaAmount: parse(draft.longDcaAmount, "DCA-bedrag LONG"), shortDcaAmount: parse(draft.shortDcaAmount, "DCA-bedrag SHORT"),
        maxDcaLong: maxLong, maxDcaShort: maxShort, longMaxDca: maxLong, shortMaxDca: maxShort,
        longTakeProfitValue: parse(draft.longTp, "TP LONG") / 100, shortTakeProfitValue: parse(draft.shortTp, "TP SHORT") / 100,
        takeProfitLong: parse(draft.longTp, "TP LONG") / 100, takeProfitShort: parse(draft.shortTp, "TP SHORT") / 100,
        // Legacy aliases remain deterministic for old clients, but the backend
        // executes the explicit LONG/SHORT fields above.
        dcaDistance: longDistance, dcaMarginUsd: parse(draft.longDcaAmount, "DCA-bedrag LONG"), maxDca: maxLong,
        takeProfit: parse(draft.longTp, "TP LONG") / 100, takeProfitEnabled: draft.mode === "PER_TRADE",
      };
      await authenticatedRequest("/api/exchanges/aster/strategy2/settings", { method: "PUT", body: JSON.stringify({ settings: next }) });
      setBase(next); setMessage(`Opgeslagen · ${summary}. Actieve posities en DCA-counts zijn niet gereset.`);
      await load(); document.dispatchEvent(new Event("visibilitychange"));
    } catch (error) { setMessage(error instanceof Error ? error.message : "Opslaan is mislukt."); }
    finally { setBusy(false); }
  }

  if (!open) return null;
  return <div role="dialog" aria-modal="true" aria-label="LONG SHORT en Take Profit instellingen" style={{ position: "fixed", inset: 0, zIndex: 10020, background: "rgba(0,0,0,.80)", backdropFilter: "blur(9px)", display: "flex", justifyContent: "center", alignItems: "flex-end" }}>
    <section style={{ width: "min(100%,720px)", maxHeight: "92dvh", overflowY: "auto", padding: "20px 17px calc(24px + env(safe-area-inset-bottom))", borderRadius: "24px 24px 0 0", border: "1px solid rgba(88,240,174,.25)", background: "linear-gradient(180deg,#07100e,#020504)", color: "#f5f7f6" }}>
      <header style={{ display: "flex", justifyContent: "space-between", gap: 14, marginBottom: 16 }}><div><small style={{ color: "#58f0ae", fontWeight: 850, letterSpacing: ".12em" }}>BOTINSTELLINGEN</small><h2 style={{ margin: "4px 0 2px" }}>LONG / SHORT · DCA & Take Profit</h2><p style={{ margin: 0, color: "#94a39c", fontSize: 13 }}>Wijzigingen gelden direct voor toekomstige acties; actieve fills, avg entry en DCA-count blijven intact.</p></div><button type="button" aria-label="Sluiten" onClick={() => setOpen(false)} style={{ width: 42, height: 42, borderRadius: 13, border: "1px solid #34433d", background: "#101713", color: "white", fontSize: 24 }}>×</button></header>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 7, marginBottom: 14 }}>
        {(["PER_TRADE", "PORTFOLIO", "OFF"] as TpMode[]).map((mode) => <button key={mode} type="button" onClick={() => setDraft((d) => ({ ...d, mode }))} style={{ minHeight: 48, borderRadius: 12, border: draft.mode === mode ? "1px solid #58f0ae" : "1px solid #28362f", background: draft.mode === mode ? "rgba(88,240,174,.12)" : "#0a0f0d", color: draft.mode === mode ? "#8cf5bd" : "#abb6b0", fontWeight: 850 }}>{mode === "PER_TRADE" ? "Per trade" : mode === "PORTFOLIO" ? "Portfolio" : "Uit"}</button>)}
      </div>

      {draft.mode === "OFF" && <p style={{ padding: 12, borderRadius: 12, background: "rgba(255,255,255,.035)", color: "#c4ccc8" }}><b>Automatische Take Profit uitgeschakeld.</b><br /><small>DCA en overige strategie-logica blijven normaal doorlopen.</small></p>}
      {draft.mode === "PORTFOLIO" && <div style={{ display: "grid", gap: 10, padding: 13, borderRadius: 14, border: "1px solid rgba(112,169,255,.26)", background: "rgba(35,77,120,.10)", marginBottom: 14 }}>
        <Field label="Portfolio TP" value={draft.portfolioTp} onChange={(value) => setDraft((d) => ({ ...d, portfolioTp: value }))} suffix="%" />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, fontSize: 12 }}><span>Cycle Start<br /><b>${cycleStart ? cycleStart.toFixed(2) : "—"}</b></span><span>Portfolio Target<br /><b>${selectedTarget ? selectedTarget.toFixed(2) : "—"}</b></span><span>Current Equity<br /><b>${currentEquity ? currentEquity.toFixed(2) : "—"}</b></span><span>Afstand<br /><b>${distanceUsd.toFixed(2)} / {distancePct.toFixed(2)}%</b></span></div>
        <small style={{ color: "#91a7bb" }}>Cycle status: {String(cycle.cycleStatus || "RUNNING")}</small>
        {warning && <p role="alert" style={{ margin: 0, padding: 11, borderRadius: 10, background: "rgba(255,153,74,.12)", color: "#ffbd86", fontWeight: 750 }}>De huidige portfolio-equity ligt al boven het ingestelde target. Na opslaan kan direct een volledige portfolio-exit starten.</p>}
      </div>}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <section style={{ padding: 13, borderRadius: 14, border: "1px solid rgba(88,240,174,.23)", background: "rgba(88,240,174,.035)", display: "grid", gap: 10 }}><b style={{ color: "#66efb0" }}>LONG</b><Field label="DCA-afstand LONG" value={draft.longDcaDistance} onChange={(value) => setDraft((d) => ({ ...d, longDcaDistance: value }))} suffix="%" /><Field label="DCA-bedrag LONG" value={draft.longDcaAmount} onChange={(value) => setDraft((d) => ({ ...d, longDcaAmount: value }))} suffix="USDT" /><Field label="Max DCA LONG" value={draft.maxDcaLong} onChange={(value) => setDraft((d) => ({ ...d, maxDcaLong: value }))} suffix="" /><Field label="Take Profit LONG" value={draft.longTp} onChange={(value) => setDraft((d) => ({ ...d, longTp: value }))} suffix="%" disabled={!individualActive} />{!individualActive && <small style={{ color: "#d0a765" }}>Niet actief in {draft.mode === "PORTFOLIO" ? "Portfolio" : "Uit"}-modus</small>}</section>
        <section style={{ padding: 13, borderRadius: 14, border: "1px solid rgba(255,104,130,.23)", background: "rgba(255,104,130,.035)", display: "grid", gap: 10 }}><b style={{ color: "#ff8ba0" }}>SHORT</b><Field label="DCA-afstand SHORT" value={draft.shortDcaDistance} onChange={(value) => setDraft((d) => ({ ...d, shortDcaDistance: value }))} suffix="%" /><Field label="DCA-bedrag SHORT" value={draft.shortDcaAmount} onChange={(value) => setDraft((d) => ({ ...d, shortDcaAmount: value }))} suffix="USDT" /><Field label="Max DCA SHORT" value={draft.maxDcaShort} onChange={(value) => setDraft((d) => ({ ...d, maxDcaShort: value }))} suffix="" /><Field label="Take Profit SHORT" value={draft.shortTp} onChange={(value) => setDraft((d) => ({ ...d, shortTp: value }))} suffix="%" disabled={!individualActive} />{!individualActive && <small style={{ color: "#d0a765" }}>Niet actief in {draft.mode === "PORTFOLIO" ? "Portfolio" : "Uit"}-modus</small>}</section>
      </div>

      {message && <p role="status" style={{ padding: 11, borderRadius: 10, background: "rgba(88,240,174,.07)", color: /mislukt|ongeldig|fout/i.test(message) ? "#ff8d9e" : "#8cf5bd", fontSize: 13 }}>{message}</p>}
      <footer style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 9, marginTop: 14 }}><button type="button" disabled={busy} onClick={() => { setDraft(buildDraft(base)); setMessage(""); }} style={{ minHeight: 49, borderRadius: 12, border: "1px solid #38463f", background: "#101613", color: "#d6ddd9", fontWeight: 850 }}>Terugzetten</button><button type="button" disabled={busy} onClick={save} style={{ minHeight: 49, borderRadius: 12, border: "1px solid #58f0ae", background: "#0c3928", color: "#8cf5bd", fontWeight: 900 }}>{busy ? "Opslaan…" : "Opslaan"}</button></footer>
    </section>
  </div>;
}
