"use client";

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
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

const pct = (value: unknown, fallback: number) => {
  const n = Number(value); return String((Number.isFinite(n) ? n : fallback) * 100);
};
const num = (value: unknown, fallback: number) => {
  const n = Number(value); return String(Number.isFinite(n) ? n : fallback);
};
const parsed = (value: string, label: string, allowZero = false) => {
  const n = Number(value.replace(",", "."));
  if (!Number.isFinite(n) || (allowZero ? n < 0 : n <= 0)) throw new Error(`${label} is ongeldig.`);
  return n;
};

function draftFrom(settings: Settings): Draft {
  const distance = settings.dcaDistance ?? .003;
  const amount = settings.dcaMarginUsd ?? 2;
  const max = settings.maxDca ?? 3;
  const tp = settings.takeProfit ?? .015;
  const rawMode = String(settings.takeProfitMode || (settings.takeProfitEnabled === false ? "OFF" : "PER_TRADE")).toUpperCase();
  const mode: TpMode = rawMode === "PORTFOLIO" ? "PORTFOLIO" : rawMode === "OFF" ? "OFF" : "PER_TRADE";
  return {
    longDcaDistance: pct(settings.longDcaDistance ?? distance, .003),
    shortDcaDistance: pct(settings.shortDcaDistance ?? distance, .003),
    longDcaAmount: num(settings.longDcaMarginUsd ?? settings.longDcaAmount ?? amount, 2),
    shortDcaAmount: num(settings.shortDcaMarginUsd ?? settings.shortDcaAmount ?? amount, 2),
    maxDcaLong: num(settings.maxDcaLong ?? settings.longMaxDca ?? max, 3),
    maxDcaShort: num(settings.maxDcaShort ?? settings.shortMaxDca ?? max, 3),
    longTp: pct(settings.longTakeProfitValue ?? settings.takeProfitLong ?? tp, .015),
    shortTp: pct(settings.shortTakeProfitValue ?? settings.takeProfitShort ?? tp, .015),
    mode,
    portfolioTp: num(settings.portfolioTpPercent, 20),
  };
}

function InlineField({ label, value, suffix, onChange, disabled = false }: { label: string; value: string; suffix?: string; onChange: (value: string) => void; disabled?: boolean }) {
  return <label style={{ display: "grid", gap: 6, opacity: disabled ? .5 : 1 }}>
    <span style={{ color: "#a8b2ae", fontSize: 12, fontWeight: 780 }}>{label}</span>
    <span style={{ minHeight: 52, display: "flex", alignItems: "center", overflow: "hidden", border: "1px solid rgba(205,188,139,.18)", borderRadius: 13, background: "linear-gradient(180deg,rgba(28,34,31,.98),rgba(16,22,19,.98))" }}>
      <input disabled={disabled} value={value} inputMode="decimal" onChange={(e) => onChange(e.target.value.replace(",", "."))} style={{ width: "100%", minWidth: 0, border: 0, outline: 0, background: "transparent", color: "#f5f3ec", padding: "12px 14px", fontSize: 17, fontWeight: 700 }} />
      {suffix ? <b style={{ paddingRight: 12, color: "#c7b77d", fontSize: 11 }}>{suffix}</b> : null}
    </span>
  </label>;
}

export function AsterInlineStrategySettings() {
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [message, setMessage] = useState("");
  const [base, setBase] = useState<Settings>({});
  const [cycle, setCycle] = useState<Cycle>({});
  const [draft, setDraft] = useState<Draft>(() => draftFrom({}));

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const payload = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" }) as Record<string, unknown>;
      const strategy2 = payload.strategy2 && typeof payload.strategy2 === "object" ? payload.strategy2 as Record<string, unknown> : {};
      const settings = strategy2.settings && typeof strategy2.settings === "object" ? strategy2.settings as Settings : {};
      const report = strategy2.multiBbReport && typeof strategy2.multiBbReport === "object" ? strategy2.multiBbReport as Record<string, unknown> : strategy2.report && typeof strategy2.report === "object" ? strategy2.report as Record<string, unknown> : {};
      const portfolioCycle = report.portfolioCycle && typeof report.portfolioCycle === "object" ? report.portfolioCycle as Cycle : {};
      setBase(settings); setDraft(draftFrom(settings)); setCycle(portfolioCycle); setLoaded(true); setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Instellingen konden niet worden geladen.");
    } finally { setBusy(false); }
  }, []);

  useEffect(() => {
    let active = true;
    const install = () => {
      const maker = document.getElementById("strategy-2-maker");
      const grid = maker?.querySelector(".maker-input.compact-settings-grid") as HTMLElement | null;
      if (!grid) return;
      let node = grid.querySelector("[data-inline-side-settings-host]") as HTMLElement | null;
      if (!node) {
        node = document.createElement("div");
        node.setAttribute("data-inline-side-settings-host", "true");
        Object.assign(node.style, { gridColumn: "1 / -1", width: "100%" });
        const advanced = grid.querySelector("[data-side-tp-settings]");
        const asym = grid.querySelector(":scope > .asym-hedge-card");
        grid.insertBefore(node, advanced || asym || null);
      }
      if (active) setHost(node);
      const advanced = grid.querySelector("[data-side-tp-settings]") as HTMLButtonElement | null;
      if (advanced) {
        advanced.textContent = "Geavanceerd LONG / SHORT";
        Object.assign(advanced.style, { minHeight: "42px", width: "auto", justifySelf: "start", padding: "8px 14px", fontSize: "12px", borderRadius: "11px", letterSpacing: "0" });
      }
    };
    install();
    const observer = new MutationObserver(install);
    observer.observe(document.body, { subtree: true, childList: true });
    return () => { active = false; observer.disconnect(); };
  }, []);

  useEffect(() => {
    if (host && !loaded) void load();
  }, [host, loaded, load]);

  useEffect(() => {
    const refresh = () => { if (host) void load(); };
    document.addEventListener("visibilitychange", refresh);
    return () => document.removeEventListener("visibilitychange", refresh);
  }, [host, load]);

  async function save() {
    if (busy) return;
    setBusy(true); setMessage("");
    try {
      const longDistance = parsed(draft.longDcaDistance, "DCA-afstand LONG") / 100;
      const shortDistance = parsed(draft.shortDcaDistance, "DCA-afstand SHORT") / 100;
      if (longDistance > .50 || shortDistance > .50) throw new Error("DCA-afstand mag maximaal 50% zijn.");
      const maxLong = Math.round(parsed(draft.maxDcaLong, "Max DCA LONG", true));
      const maxShort = Math.round(parsed(draft.maxDcaShort, "Max DCA SHORT", true));
      if (maxLong > 500 || maxShort > 500) throw new Error("Max DCA mag maximaal 500 zijn.");
      const latest = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" }) as Record<string, unknown>;
      const strategy2 = latest.strategy2 && typeof latest.strategy2 === "object" ? latest.strategy2 as Record<string, unknown> : {};
      const settings = strategy2.settings && typeof strategy2.settings === "object" ? strategy2.settings as Settings : base;
      const longAmount = parsed(draft.longDcaAmount, "DCA-bedrag LONG");
      const shortAmount = parsed(draft.shortDcaAmount, "DCA-bedrag SHORT");
      const longTp = parsed(draft.longTp, "TP LONG") / 100;
      const shortTp = parsed(draft.shortTp, "TP SHORT") / 100;
      const next = {
        ...settings,
        takeProfitMode: draft.mode,
        portfolioTpPercent: parsed(draft.portfolioTp, "Portfolio TP"),
        longDcaDistance: longDistance, shortDcaDistance: shortDistance,
        longDcaMarginUsd: longAmount, shortDcaMarginUsd: shortAmount,
        longDcaAmount: longAmount, shortDcaAmount: shortAmount,
        maxDcaLong: maxLong, maxDcaShort: maxShort, longMaxDca: maxLong, shortMaxDca: maxShort,
        longTakeProfitValue: longTp, shortTakeProfitValue: shortTp,
        takeProfitLong: longTp, takeProfitShort: shortTp,
        dcaDistance: longDistance, dcaMarginUsd: longAmount, maxDca: maxLong,
        takeProfit: longTp, takeProfitEnabled: draft.mode === "PER_TRADE",
      };
      await authenticatedRequest("/api/exchanges/aster/strategy2/settings", { method: "PUT", body: JSON.stringify({ settings: next }) });
      setBase(next); setMessage("Opgeslagen. Actieve posities en DCA-counts blijven intact.");
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Opslaan is mislukt.");
    } finally { setBusy(false); }
  }

  if (!host) return null;
  const cycleStart = Number(cycle.cycleStartEquity || 0);
  const current = Number(cycle.currentEquity || 0);
  const portfolioPct = Number(draft.portfolioTp.replace(",", ".")) || 0;
  const target = cycleStart > 0 ? cycleStart * (1 + portfolioPct / 100) : Number(cycle.targetEquity || 0);
  const remaining = target > 0 ? Math.max(0, target - current) : 0;

  return createPortal(<section data-inline-strategy-settings style={{ margin: "4px 0 8px", padding: "14px", border: "1px solid rgba(205,181,101,.20)", borderRadius: 17, background: "linear-gradient(180deg,rgba(5,18,13,.88),rgba(3,10,8,.90))", display: "grid", gap: 12 }}>
    <div style={{ display: "flex", alignItems: "end", justifyContent: "space-between", gap: 10 }}>
      <div><div style={{ color: "#d3b451", fontWeight: 900, fontSize: 13 }}>LONG / SHORT</div><div style={{ color: "#8f9b96", fontSize: 11 }}>Algemene DCA- en Take Profit-instellingen</div></div>
      {busy ? <small style={{ color: "#8f9b96" }}>Laden…</small> : null}
    </div>

    <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 7 }}>
      {(["PER_TRADE", "PORTFOLIO", "OFF"] as TpMode[]).map((mode) => <button key={mode} type="button" onClick={() => setDraft((d) => ({ ...d, mode }))} style={{ minHeight: 42, borderRadius: 11, border: draft.mode === mode ? "1px solid #d4b451" : "1px solid rgba(255,255,255,.12)", background: draft.mode === mode ? "rgba(212,180,81,.13)" : "rgba(255,255,255,.035)", color: draft.mode === mode ? "#efd67f" : "#a9b0ad", fontWeight: 820, fontSize: 12 }}>{mode === "PER_TRADE" ? "Per trade" : mode === "PORTFOLIO" ? "Portfolio" : "Uit"}</button>)}
    </div>

    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 9 }}>
      <InlineField label="DCA-afstand LONG" value={draft.longDcaDistance} suffix="%" onChange={(v) => setDraft((d) => ({ ...d, longDcaDistance: v }))} />
      <InlineField label="DCA-afstand SHORT" value={draft.shortDcaDistance} suffix="%" onChange={(v) => setDraft((d) => ({ ...d, shortDcaDistance: v }))} />
      <InlineField label="DCA-bedrag LONG" value={draft.longDcaAmount} suffix="USDT" onChange={(v) => setDraft((d) => ({ ...d, longDcaAmount: v }))} />
      <InlineField label="DCA-bedrag SHORT" value={draft.shortDcaAmount} suffix="USDT" onChange={(v) => setDraft((d) => ({ ...d, shortDcaAmount: v }))} />
      <InlineField label="Max DCA LONG" value={draft.maxDcaLong} onChange={(v) => setDraft((d) => ({ ...d, maxDcaLong: v }))} />
      <InlineField label="Max DCA SHORT" value={draft.maxDcaShort} onChange={(v) => setDraft((d) => ({ ...d, maxDcaShort: v }))} />
    </div>

    {draft.mode === "PER_TRADE" ? <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 9 }}>
      <InlineField label="Take Profit LONG" value={draft.longTp} suffix="%" onChange={(v) => setDraft((d) => ({ ...d, longTp: v }))} />
      <InlineField label="Take Profit SHORT" value={draft.shortTp} suffix="%" onChange={(v) => setDraft((d) => ({ ...d, shortTp: v }))} />
    </div> : null}

    {draft.mode === "PORTFOLIO" ? <div style={{ display: "grid", gap: 9 }}>
      <InlineField label="Portfolio Take Profit" value={draft.portfolioTp} suffix="%" onChange={(v) => setDraft((d) => ({ ...d, portfolioTp: v }))} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 6, color: "#a7b1ad", fontSize: 10 }}>
        <span>START<br /><b style={{ color: "#eee" }}>${cycleStart ? cycleStart.toFixed(2) : "—"}</b></span>
        <span>TARGET<br /><b style={{ color: "#eee" }}>${target ? target.toFixed(2) : "—"}</b></span>
        <span>NOG<br /><b style={{ color: "#eee" }}>${remaining.toFixed(2)}</b></span>
      </div>
    </div> : null}

    {draft.mode === "OFF" ? <div style={{ color: "#9ba59f", fontSize: 11 }}>Automatische Take Profit staat uit. DCA blijft normaal actief.</div> : null}

    {message ? <div role="status" style={{ color: /mislukt|ongeldig|fout/i.test(message) ? "#ff8d9e" : "#8cf5bd", fontSize: 11 }}>{message}</div> : null}
    <button type="button" disabled={busy} onClick={save} style={{ minHeight: 45, borderRadius: 12, border: "1px solid rgba(212,180,81,.55)", background: "linear-gradient(135deg,rgba(70,51,8,.92),rgba(15,31,20,.95))", color: "#f0d675", fontWeight: 900 }}>{busy ? "Opslaan…" : "LONG / SHORT opslaan"}</button>
  </section>, host);
}
