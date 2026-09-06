"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

type Settings = Record<string, unknown>;
type Override = Record<string, unknown>;
type FieldKey = "entryMarginUsd" | "minimumLeverage" | "dcaMarginUsd" | "dcaDistance" | "maxDca" | "takeProfit" | "takeProfitEnabled" | "shortStartMultiplier";

type Draft = {
  entryMarginUsd: string;
  minimumLeverage: string;
  dcaMarginUsd: string;
  dcaDistance: string;
  maxDca: string;
  takeProfit: string;
  takeProfitEnabled: boolean;
  shortStartMultiplier: string;
};

const numericFields: Array<{ key: Exclude<FieldKey, "takeProfitEnabled">; label: string; suffix: string; nextCycle?: boolean }> = [
  { key: "entryMarginUsd", label: "Instapbedrag / margin", suffix: "USDT", nextCycle: true },
  { key: "minimumLeverage", label: "Minimale leverage", suffix: "x", nextCycle: true },
  { key: "dcaMarginUsd", label: "DCA-bedrag / margin", suffix: "USDT" },
  { key: "dcaDistance", label: "DCA-afstand", suffix: "%" },
  { key: "maxDca", label: "Maximaal aantal DCA's", suffix: "" },
  { key: "takeProfit", label: "Take Profit", suffix: "%" },
  { key: "shortStartMultiplier", label: "SHORT start-multiplier", suffix: "x", nextCycle: true },
];

function normalizeSymbol(value: string) {
  return value.toUpperCase().replace(/[\s/_-]/g, "").replace(/[^A-Z0-9]/g, "");
}

function currentPairFromDom() {
  const marker = Array.from(document.querySelectorAll("span")).find((node) => node.textContent?.trim() === "ASTER · TRADEDETAIL");
  const header = marker?.closest("header");
  const title = header?.querySelector("h2")?.textContent || "";
  const compact = normalizeSymbol(title);
  if (compact.endsWith("USDT")) return compact;
  const base = compact.replace(/USDT$/, "");
  return base ? `${base}USDT` : "";
}

function pctToInput(value: unknown, fallback: number) {
  const n = Number(value);
  return String((Number.isFinite(n) ? n : fallback) * 100);
}

function numberInput(value: unknown, fallback: number) {
  const n = Number(value);
  return String(Number.isFinite(n) ? n : fallback);
}

function buildDraft(base: Settings, override: Override): Draft {
  return {
    entryMarginUsd: numberInput(override.entryMarginUsd ?? base.entryMarginUsd, 5),
    minimumLeverage: numberInput(override.minimumLeverage ?? base.minimumLeverage, 50),
    dcaMarginUsd: numberInput(override.dcaMarginUsd ?? base.dcaMarginUsd, 2),
    dcaDistance: pctToInput(override.dcaDistance ?? base.dcaDistance, .003),
    maxDca: numberInput(override.maxDca ?? base.maxDca, 3),
    takeProfit: pctToInput(override.takeProfit ?? base.takeProfit, .015),
    takeProfitEnabled: Boolean(override.takeProfitEnabled ?? base.takeProfitEnabled ?? true),
    shortStartMultiplier: numberInput(override.shortStartMultiplier ?? base.shortStartMultiplier, 5),
  };
}

function parsePositive(value: string, label: string) {
  const n = Number(value.replace(",", "."));
  if (!Number.isFinite(n) || n <= 0) throw new Error(`${label} moet groter dan 0 zijn.`);
  return n;
}

export function AsterPairSettingsOverlay() {
  const [symbol, setSymbol] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [base, setBase] = useState<Settings>({});
  const [draft, setDraft] = useState<Draft>(() => buildDraft({}, {}));
  const [customEnabled, setCustomEnabled] = useState(false);
  const [enabledFields, setEnabledFields] = useState<Set<FieldKey>>(new Set());

  const load = useCallback(async (target: string) => {
    setBusy(true); setMessage("");
    try {
      const payload = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" }) as Record<string, unknown>;
      const strategy2 = payload.strategy2 && typeof payload.strategy2 === "object" ? payload.strategy2 as Record<string, unknown> : {};
      const settings = strategy2.settings && typeof strategy2.settings === "object" ? strategy2.settings as Settings : {};
      const allOverrides = settings.pairOverrides && typeof settings.pairOverrides === "object" ? settings.pairOverrides as Record<string, Override> : {};
      const override = allOverrides[target] && typeof allOverrides[target] === "object" ? allOverrides[target] : {};
      const keys = new Set<FieldKey>((Object.keys(override) as FieldKey[]).filter((key) => key !== "enabled" && ["entryMarginUsd", "minimumLeverage", "dcaMarginUsd", "dcaDistance", "maxDca", "takeProfit", "takeProfitEnabled", "shortStartMultiplier"].includes(key)));
      setBase(settings);
      setDraft(buildDraft(settings, override));
      setEnabledFields(keys);
      setCustomEnabled(keys.size > 0 && override.enabled !== false);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Pair-instellingen konden niet worden geladen.");
    } finally { setBusy(false); }
  }, []);

  const launch = useCallback(() => {
    const pair = currentPairFromDom();
    if (!pair) return;
    setSymbol(pair); setOpen(true); void load(pair);
  }, [load]);

  useEffect(() => {
    let stopped = false;
    const install = () => {
      if (stopped) return;
      const labels = Array.from(document.querySelectorAll("span"));
      const label = labels.find((node) => node.textContent?.trim() === "MARGIN IN TRADE");
      const cell = label?.parentElement;
      if (!cell || cell.querySelector("[data-pair-settings-pencil]")) return;
      cell.style.position = "relative";
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("data-pair-settings-pencil", "true");
      button.setAttribute("aria-label", "Instellingen voor deze pair aanpassen");
      button.title = "Pair-instellingen aanpassen";
      button.innerHTML = "✎";
      Object.assign(button.style, {
        position: "absolute", right: "10px", top: "9px", width: "34px", height: "34px", borderRadius: "11px",
        border: "1px solid rgba(88,240,174,.42)", background: "rgba(7,22,18,.92)", color: "#69efb1", fontSize: "20px",
        lineHeight: "30px", textAlign: "center", cursor: "pointer", zIndex: "4", boxShadow: "0 0 18px rgba(88,240,174,.10)",
      });
      button.addEventListener("click", launch);
      cell.appendChild(button);
    };
    install();
    const observer = new MutationObserver(install);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => { stopped = true; observer.disconnect(); document.querySelectorAll("[data-pair-settings-pencil]").forEach((node) => node.remove()); };
  }, [launch]);

  const pairLabel = useMemo(() => symbol.endsWith("USDT") ? `${symbol.slice(0, -4)}/USDT` : symbol, [symbol]);

  const toggleField = (key: FieldKey) => setEnabledFields((current) => {
    const next = new Set(current);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });

  async function save() {
    if (!symbol || busy) return;
    setBusy(true); setMessage("");
    try {
      const latest = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" }) as Record<string, unknown>;
      const strategy2 = latest.strategy2 && typeof latest.strategy2 === "object" ? latest.strategy2 as Record<string, unknown> : {};
      const settings = strategy2.settings && typeof strategy2.settings === "object" ? strategy2.settings as Settings : base;
      const previous = settings.pairOverrides && typeof settings.pairOverrides === "object" ? settings.pairOverrides as Record<string, Override> : {};
      const nextOverrides: Record<string, Override> = { ...previous };
      if (!customEnabled) {
        delete nextOverrides[symbol];
      } else {
        const override: Override = { enabled: true };
        if (enabledFields.has("entryMarginUsd")) override.entryMarginUsd = parsePositive(draft.entryMarginUsd, "Instapbedrag");
        if (enabledFields.has("minimumLeverage")) {
          const value = Math.round(parsePositive(draft.minimumLeverage, "Leverage"));
          if (value < 1 || value > 300) throw new Error("Leverage moet tussen 1x en 300x liggen.");
          override.minimumLeverage = value;
        }
        if (enabledFields.has("dcaMarginUsd")) override.dcaMarginUsd = parsePositive(draft.dcaMarginUsd, "DCA-bedrag");
        if (enabledFields.has("dcaDistance")) {
          const value = parsePositive(draft.dcaDistance, "DCA-afstand") / 100;
          if (value < .0001 || value > .50) throw new Error("DCA-afstand moet tussen 0,01% en 50% liggen.");
          override.dcaDistance = value;
        }
        if (enabledFields.has("maxDca")) {
          const value = Math.round(Number(draft.maxDca.replace(",", ".")));
          if (!Number.isFinite(value) || value < 0 || value > 500) throw new Error("Max DCA moet tussen 0 en 500 liggen.");
          override.maxDca = value;
        }
        if (enabledFields.has("takeProfit")) override.takeProfit = parsePositive(draft.takeProfit, "Take Profit") / 100;
        if (enabledFields.has("takeProfitEnabled")) override.takeProfitEnabled = draft.takeProfitEnabled;
        if (enabledFields.has("shortStartMultiplier")) {
          const value = parsePositive(draft.shortStartMultiplier, "SHORT multiplier");
          if (value < 1 || value > 10) throw new Error("SHORT multiplier moet tussen 1x en 10x liggen.");
          override.shortStartMultiplier = value;
        }
        if (Object.keys(override).length === 1) delete nextOverrides[symbol];
        else nextOverrides[symbol] = override;
      }
      const result = await authenticatedRequest("/api/exchanges/aster/strategy2/settings", {
        method: "PUT",
        body: JSON.stringify({ settings: { ...settings, pairOverrides: nextOverrides } }),
      }) as Record<string, unknown>;
      const confirmed = result.strategy2 && typeof result.strategy2 === "object" ? result.strategy2 as Record<string, unknown> : null;
      if (!confirmed) throw new Error("Server heeft de pair-instellingen niet bevestigd.");
      setBase(settings);
      setMessage(customEnabled ? `${pairLabel}: aangepaste instellingen opgeslagen.` : `${pairLabel}: basisinstellingen hersteld.`);
      window.setTimeout(() => window.dispatchEvent(new Event("focus")), 0);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Opslaan is mislukt.");
    } finally { setBusy(false); }
  }

  if (!open) return null;
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 10000, background: "rgba(0,0,0,.78)", backdropFilter: "blur(8px)", display: "flex", alignItems: "flex-end", justifyContent: "center" }} role="dialog" aria-modal="true" aria-label={`${pairLabel} pair-instellingen`}>
      <section style={{ width: "min(100%,680px)", maxHeight: "90dvh", overflowY: "auto", borderRadius: "24px 24px 0 0", border: "1px solid rgba(88,240,174,.22)", background: "linear-gradient(180deg,#07100e 0%,#020706 100%)", color: "#f5f7f6", padding: "20px 18px calc(24px + env(safe-area-inset-bottom))", boxShadow: "0 -24px 80px rgba(0,0,0,.65)" }}>
        <header style={{ display: "flex", justifyContent: "space-between", gap: 14, alignItems: "start", marginBottom: 16 }}>
          <div><small style={{ color: "#58f0ae", letterSpacing: ".14em", fontWeight: 800 }}>PAIR OVERRIDE</small><h2 style={{ margin: "5px 0 2px", fontSize: 25 }}>{pairLabel} · instellingen</h2><p style={{ margin: 0, color: "#9aa7a1", fontSize: 13 }}>Alleen deze munt wijkt af. Niet-aangevinkte velden blijven de basissettings volgen.</p></div>
          <button type="button" onClick={() => setOpen(false)} style={{ width: 42, height: 42, flex: "0 0 auto", borderRadius: 13, border: "1px solid #32423b", background: "#152019", color: "white", fontSize: 24 }}>×</button>
        </header>

        <label style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, padding: "14px", borderRadius: 15, border: "1px solid #24372e", background: "rgba(255,255,255,.025)", marginBottom: 12 }}>
          <span><b>Gebruik aangepaste instellingen</b><small style={{ display: "block", color: "#91a098", marginTop: 3 }}>Pair override → basissetting → systeemdefault</small></span>
          <input type="checkbox" checked={customEnabled} onChange={(e) => setCustomEnabled(e.target.checked)} style={{ width: 24, height: 24, accentColor: "#58f0ae" }} />
        </label>

        <div style={{ display: "grid", gap: 9, opacity: customEnabled ? 1 : .48, pointerEvents: customEnabled ? "auto" : "none" }}>
          {numericFields.map(({ key, label, suffix, nextCycle }) => (
            <div key={key} style={{ display: "grid", gridTemplateColumns: "28px 1fr minmax(105px,145px)", gap: 9, alignItems: "center", padding: "10px 11px", border: enabledFields.has(key) ? "1px solid rgba(88,240,174,.38)" : "1px solid #1b2923", borderRadius: 13, background: enabledFields.has(key) ? "rgba(88,240,174,.055)" : "rgba(255,255,255,.018)" }}>
              <input aria-label={`${label} overschrijven`} type="checkbox" checked={enabledFields.has(key)} onChange={() => toggleField(key)} style={{ width: 20, height: 20, accentColor: "#58f0ae" }} />
              <span style={{ fontSize: 13, fontWeight: 700 }}>{label}{nextCycle && <small style={{ display: "block", color: "#c6a55a", fontWeight: 600, marginTop: 2 }}>Geldt vanaf volgende nieuwe cyclus</small>}</span>
              <label style={{ display: "flex", alignItems: "center", gap: 5, border: "1px solid #31463b", borderRadius: 9, padding: "7px 8px", background: "#020604" }}>
                <input value={draft[key]} inputMode="decimal" onFocus={() => { if (!enabledFields.has(key)) setEnabledFields((s) => new Set(s).add(key)); }} onChange={(e) => { setDraft((current) => ({ ...current, [key]: e.target.value })); if (!enabledFields.has(key)) setEnabledFields((s) => new Set(s).add(key)); }} style={{ width: "100%", minWidth: 0, border: 0, outline: 0, background: "transparent", color: "white", fontSize: 15, fontWeight: 800, textAlign: "right" }} />
                <small style={{ color: "#86978e" }}>{suffix}</small>
              </label>
            </div>
          ))}

          <div style={{ display: "grid", gridTemplateColumns: "28px 1fr auto", gap: 9, alignItems: "center", padding: "10px 11px", border: enabledFields.has("takeProfitEnabled") ? "1px solid rgba(88,240,174,.38)" : "1px solid #1b2923", borderRadius: 13 }}>
            <input type="checkbox" checked={enabledFields.has("takeProfitEnabled")} onChange={() => toggleField("takeProfitEnabled")} style={{ width: 20, height: 20, accentColor: "#58f0ae" }} />
            <b style={{ fontSize: 13 }}>Take Profit actief</b>
            <input type="checkbox" checked={draft.takeProfitEnabled} onChange={(e) => { setDraft((d) => ({ ...d, takeProfitEnabled: e.target.checked })); setEnabledFields((s) => new Set(s).add("takeProfitEnabled")); }} style={{ width: 24, height: 24, accentColor: "#58f0ae" }} />
          </div>
        </div>

        <p style={{ color: "#8d9b94", fontSize: 12, lineHeight: 1.45, margin: "13px 2px" }}>Max DCA, DCA-bedrag/-afstand en TP gelden voor toekomstige acties van een reeds geopende positie. Uitgevoerde fills worden nooit achteraf aangepast. Instapbedrag, leverage en startmultiplier gelden pas bij een nieuwe cyclus.</p>
        {message && <p role="status" style={{ padding: "10px 12px", borderRadius: 10, background: "rgba(88,240,174,.07)", color: message.toLowerCase().includes("mislukt") ? "#ff8d9e" : "#8cf5bd", fontSize: 13 }}>{message}</p>}
        <footer style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 13 }}>
          <button type="button" disabled={busy} onClick={() => { setCustomEnabled(false); setEnabledFields(new Set()); }} style={{ minHeight: 48, borderRadius: 12, border: "1px solid #39453f", background: "#101613", color: "#d4dbd7", fontWeight: 800 }}>Herstel basisinstellingen</button>
          <button type="button" disabled={busy} onClick={save} style={{ minHeight: 48, borderRadius: 12, border: "1px solid #58f0ae", background: "#0d3928", color: "#8cf5bd", fontWeight: 900 }}>{busy ? "Opslaan…" : "Pair opslaan"}</button>
        </footer>
      </section>
    </div>
  );
}
