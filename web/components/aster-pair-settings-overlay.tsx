"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

type Settings = Record<string, unknown>;
type Override = Record<string, unknown>;
type Side = "LONG" | "SHORT";
type SideDraft = { dcaAmount: string; dcaDistance: string; maxDca: string; takeProfit: string };
type Draft = { entryMarginUsd: string; minimumLeverage: string; shortStartMultiplier: string; LONG: SideDraft; SHORT: SideDraft };

type SideKey = "longDcaMarginUsd" | "longDcaDistance" | "maxDcaLong" | "longTakeProfitValue" |
               "shortDcaMarginUsd" | "shortDcaDistance" | "maxDcaShort" | "shortTakeProfitValue";
type SharedKey = "entryMarginUsd" | "minimumLeverage" | "shortStartMultiplier";
type FieldKey = SideKey | SharedKey;

const allowed = new Set<FieldKey>([
  "entryMarginUsd", "minimumLeverage", "shortStartMultiplier",
  "longDcaMarginUsd", "longDcaDistance", "maxDcaLong", "longTakeProfitValue",
  "shortDcaMarginUsd", "shortDcaDistance", "maxDcaShort", "shortTakeProfitValue",
]);
const numberText = (value: unknown, fallback: number) => { const n = Number(value); return String(Number.isFinite(n) ? n : fallback); };
const pctText = (value: unknown, fallback: number) => { const n = Number(value); return String((Number.isFinite(n) ? n : fallback) * 100); };
const parsePositive = (value: string, label: string) => { const n = Number(value.replace(",", ".")); if (!Number.isFinite(n) || n <= 0) throw new Error(`${label} moet groter dan 0 zijn.`); return n; };

function normalizeSymbol(value: string) { return value.toUpperCase().replace(/[\s/_-]/g, "").replace(/[^A-Z0-9]/g, ""); }
function currentPairFromDom() {
  const marker = Array.from(document.querySelectorAll("span")).find((node) => node.textContent?.trim() === "ASTER · TRADEDETAIL");
  const title = marker?.closest("header")?.querySelector("h2")?.textContent || "";
  const compact = normalizeSymbol(title); return compact.endsWith("USDT") ? compact : compact ? `${compact}USDT` : "";
}
function effective(base: Settings, override: Override, keys: string[], fallback: unknown) {
  for (const key of keys) if (override[key] !== undefined) return override[key];
  for (const key of keys) if (base[key] !== undefined) return base[key];
  return fallback;
}
function buildDraft(base: Settings, override: Override): Draft {
  const legacyDistance = base.dcaDistance ?? .003, legacyAmount = base.dcaMarginUsd ?? 2, legacyMax = base.maxDca ?? 3, legacyTp = base.takeProfit ?? .015;
  return {
    entryMarginUsd: numberText(override.entryMarginUsd ?? base.entryMarginUsd, 5),
    minimumLeverage: numberText(override.minimumLeverage ?? base.minimumLeverage, 50),
    shortStartMultiplier: numberText(override.shortStartMultiplier ?? base.shortStartMultiplier, 5),
    LONG: {
      dcaAmount: numberText(effective(base, override, ["longDcaMarginUsd", "longDcaAmount", "dcaMarginUsd"], legacyAmount), 2),
      dcaDistance: pctText(effective(base, override, ["longDcaDistance", "dcaDistance"], legacyDistance), .003),
      maxDca: numberText(effective(base, override, ["maxDcaLong", "longMaxDca", "maxDca"], legacyMax), 3),
      takeProfit: pctText(effective(base, override, ["longTakeProfitValue", "takeProfitLong", "takeProfit"], legacyTp), .015),
    },
    SHORT: {
      dcaAmount: numberText(effective(base, override, ["shortDcaMarginUsd", "shortDcaAmount", "dcaMarginUsd"], legacyAmount), 2),
      dcaDistance: pctText(effective(base, override, ["shortDcaDistance", "dcaDistance"], legacyDistance), .003),
      maxDca: numberText(effective(base, override, ["maxDcaShort", "shortMaxDca", "maxDca"], legacyMax), 3),
      takeProfit: pctText(effective(base, override, ["shortTakeProfitValue", "takeProfitShort", "takeProfit"], legacyTp), .015),
    },
  };
}
function overrideKeys(override: Override) { return new Set<FieldKey>(Object.keys(override).filter((key) => allowed.has(key as FieldKey)) as FieldKey[]); }

function Input({ label, value, suffix, enabled, onToggle, onChange, muted }: { label: string; value: string; suffix: string; enabled: boolean; onToggle: () => void; onChange: (v: string) => void; muted?: string }) {
  return <div style={{ display: "grid", gridTemplateColumns: "25px 1fr minmax(100px,135px)", gap: 8, alignItems: "center", padding: "9px 10px", borderRadius: 12, border: enabled ? "1px solid rgba(88,240,174,.34)" : "1px solid #1e2b25", background: enabled ? "rgba(88,240,174,.045)" : "rgba(255,255,255,.015)" }}>
    <input type="checkbox" aria-label={`${label} overschrijven`} checked={enabled} onChange={onToggle} style={{ width: 19, height: 19, accentColor: "#58f0ae" }} />
    <span style={{ fontSize: 12, fontWeight: 750 }}>{label}{muted && <small style={{ display: "block", color: "#c5a25d", marginTop: 2 }}>{muted}</small>}</span>
    <label style={{ display: "flex", alignItems: "center", border: "1px solid #304139", borderRadius: 9, background: "#020604", opacity: enabled ? 1 : .55 }}><input disabled={!enabled} value={value} inputMode="decimal" onChange={(e) => onChange(e.target.value.replace(",", "."))} style={{ width: "100%", minWidth: 0, padding: "8px", border: 0, outline: 0, background: "transparent", color: "white" }} /><b style={{ paddingRight: 7, color: "#718079", fontSize: 10 }}>{suffix}</b></label>
  </div>;
}

export function AsterPairSettingsOverlay() {
  const [symbol, setSymbol] = useState(""); const [open, setOpen] = useState(false); const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");
  const [base, setBase] = useState<Settings>({}); const [draft, setDraft] = useState<Draft>(() => buildDraft({}, {}));
  const [customEnabled, setCustomEnabled] = useState(false); const [enabledFields, setEnabledFields] = useState<Set<FieldKey>>(new Set());

  const load = useCallback(async (target: string) => {
    setBusy(true); setMessage("");
    try {
      const payload = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" }) as Record<string, unknown>;
      const strategy2 = payload.strategy2 && typeof payload.strategy2 === "object" ? payload.strategy2 as Record<string, unknown> : {};
      const settings = strategy2.settings && typeof strategy2.settings === "object" ? strategy2.settings as Settings : {};
      const all = settings.pairOverrides && typeof settings.pairOverrides === "object" ? settings.pairOverrides as Record<string, Override> : {};
      const override = all[target] && typeof all[target] === "object" ? all[target] : {};
      const keys = overrideKeys(override); setBase(settings); setDraft(buildDraft(settings, override)); setEnabledFields(keys); setCustomEnabled(keys.size > 0 && override.enabled !== false);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Pair-instellingen konden niet worden geladen."); }
    finally { setBusy(false); }
  }, []);
  const launch = useCallback(() => { const pair = currentPairFromDom(); if (!pair) return; setSymbol(pair); setOpen(true); void load(pair); }, [load]);

  useEffect(() => {
    let stopped = false;
    const install = () => {
      if (stopped) return;
      const label = Array.from(document.querySelectorAll("span")).find((node) => node.textContent?.trim() === "MARGIN IN TRADE");
      const cell = label?.parentElement; if (!cell || cell.querySelector("[data-pair-settings-pencil]")) return;
      cell.style.position = "relative"; const button = document.createElement("button"); button.type = "button"; button.setAttribute("data-pair-settings-pencil", "true");
      button.setAttribute("aria-label", "Instellingen voor deze pair aanpassen"); button.title = "Pair-instellingen aanpassen"; button.textContent = "✎";
      Object.assign(button.style, { position: "absolute", right: "10px", top: "9px", width: "34px", height: "34px", borderRadius: "11px", border: "1px solid rgba(88,240,174,.42)", background: "rgba(7,22,18,.92)", color: "#69efb1", fontSize: "20px", lineHeight: "30px", textAlign: "center", cursor: "pointer", zIndex: "4" });
      button.addEventListener("click", launch); cell.appendChild(button);
    };
    install(); const observer = new MutationObserver(install); observer.observe(document.body, { childList: true, subtree: true });
    return () => { stopped = true; observer.disconnect(); document.querySelectorAll("[data-pair-settings-pencil]").forEach((node) => node.remove()); };
  }, [launch]);

  const pairLabel = useMemo(() => symbol.endsWith("USDT") ? `${symbol.slice(0, -4)}/USDT` : symbol, [symbol]);
  const tpMode = String(base.takeProfitMode || (base.takeProfitEnabled === false ? "OFF" : "PER_TRADE")).toUpperCase();
  const tpMuted = tpMode === "PORTFOLIO" ? "Niet actief in Portfolio-modus" : tpMode === "OFF" ? "Niet actief: Take Profit staat uit" : "";
  const toggle = (key: FieldKey) => setEnabledFields((current) => { const next = new Set(current); next.has(key) ? next.delete(key) : next.add(key); return next; });
  const updateSide = (side: Side, key: keyof SideDraft, value: string) => setDraft((current) => ({ ...current, [side]: { ...current[side], [key]: value } }));

  async function save() {
    if (!symbol || busy) return; setBusy(true); setMessage("");
    try {
      const latest = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" }) as Record<string, unknown>;
      const strategy2 = latest.strategy2 && typeof latest.strategy2 === "object" ? latest.strategy2 as Record<string, unknown> : {};
      const settings = strategy2.settings && typeof strategy2.settings === "object" ? strategy2.settings as Settings : base;
      const previous = settings.pairOverrides && typeof settings.pairOverrides === "object" ? settings.pairOverrides as Record<string, Override> : {};
      const nextOverrides: Record<string, Override> = { ...previous };
      if (!customEnabled) delete nextOverrides[symbol];
      else {
        const o: Override = { enabled: true };
        if (enabledFields.has("entryMarginUsd")) o.entryMarginUsd = parsePositive(draft.entryMarginUsd, "Instapmargin");
        if (enabledFields.has("minimumLeverage")) { const x = Math.round(parsePositive(draft.minimumLeverage, "Leverage")); if (x > 300) throw new Error("Leverage mag maximaal 300x zijn."); o.minimumLeverage = x; }
        if (enabledFields.has("shortStartMultiplier")) { const x = parsePositive(draft.shortStartMultiplier, "SHORT multiplier"); if (x < 1 || x > 10) throw new Error("SHORT multiplier moet tussen 1x en 10x liggen."); o.shortStartMultiplier = x; }
        for (const side of ["LONG", "SHORT"] as Side[]) {
          const p = side === "LONG" ? "long" : "short";
          const amountKey = `${p}DcaMarginUsd` as FieldKey, distanceKey = `${p}DcaDistance` as FieldKey, maxKey = side === "LONG" ? "maxDcaLong" : "maxDcaShort", tpKey = `${p}TakeProfitValue` as FieldKey;
          if (enabledFields.has(amountKey)) o[amountKey] = parsePositive(draft[side].dcaAmount, `DCA-bedrag ${side}`);
          if (enabledFields.has(distanceKey)) { const x = parsePositive(draft[side].dcaDistance, `DCA-afstand ${side}`) / 100; if (x > .50) throw new Error(`DCA-afstand ${side} mag maximaal 50% zijn.`); o[distanceKey] = x; }
          if (enabledFields.has(maxKey as FieldKey)) { const x = Math.round(Number(draft[side].maxDca)); if (!Number.isFinite(x) || x < 0 || x > 500) throw new Error(`Max DCA ${side} moet tussen 0 en 500 liggen.`); o[maxKey] = x; }
          if (enabledFields.has(tpKey)) o[tpKey] = parsePositive(draft[side].takeProfit, `Take Profit ${side}`) / 100;
        }
        if (Object.keys(o).length === 1) delete nextOverrides[symbol]; else nextOverrides[symbol] = o;
      }
      await authenticatedRequest("/api/exchanges/aster/strategy2/settings", { method: "PUT", body: JSON.stringify({ settings: { ...settings, pairOverrides: nextOverrides } }) });
      setMessage(customEnabled ? `${pairLabel}: LONG/SHORT overrides opgeslagen. Actieve DCA-counts blijven intact.` : `${pairLabel}: Gebruik algemene instellingen is actief.`);
      await load(symbol); document.dispatchEvent(new Event("visibilitychange"));
    } catch (error) { setMessage(error instanceof Error ? error.message : "Opslaan is mislukt."); }
    finally { setBusy(false); }
  }

  if (!open) return null;
  return <div style={{ position: "fixed", inset: 0, zIndex: 10030, background: "rgba(0,0,0,.80)", backdropFilter: "blur(8px)", display: "flex", alignItems: "flex-end", justifyContent: "center" }} role="dialog" aria-modal="true" aria-label={`${pairLabel} pair-instellingen`}>
    <section style={{ width: "min(100%,700px)", maxHeight: "92dvh", overflowY: "auto", borderRadius: "24px 24px 0 0", border: "1px solid rgba(88,240,174,.22)", background: "linear-gradient(180deg,#07100e,#020706)", color: "#f5f7f6", padding: "20px 17px calc(24px + env(safe-area-inset-bottom))" }}>
      <header style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 14 }}><div><small style={{ color: "#58f0ae", letterSpacing: ".14em", fontWeight: 850 }}>PAIR OVERRIDE</small><h2 style={{ margin: "4px 0" }}>{pairLabel} · instellingen</h2><p style={{ margin: 0, color: "#94a19b", fontSize: 12 }}>Eén pair-editor voor zowel LONG als SHORT. Pair override → algemene instelling → systeemdefault.</p></div><button type="button" aria-label="Sluiten" onClick={() => setOpen(false)} style={{ width: 42, height: 42, borderRadius: 13, border: "1px solid #32423b", background: "#152019", color: "white", fontSize: 24 }}>×</button></header>
      <label style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, padding: 12, border: "1px solid #273830", borderRadius: 13, marginBottom: 10 }}><span><b>Pair-specifieke instellingen</b><small style={{ display: "block", color: "#8d9b94" }}>Uit = Gebruik algemene instellingen</small></span><input type="checkbox" checked={customEnabled} onChange={(e) => setCustomEnabled(e.target.checked)} style={{ width: 24, height: 24, accentColor: "#58f0ae" }} /></label>
      <div style={{ opacity: customEnabled ? 1 : .45, pointerEvents: customEnabled ? "auto" : "none", display: "grid", gap: 10 }}>
        <section style={{ display: "grid", gap: 7, padding: 11, border: "1px solid #24342d", borderRadius: 13 }}><b>Gedeeld / volgende cycle</b><Input label="Instapmargin" value={draft.entryMarginUsd} suffix="USDT" enabled={enabledFields.has("entryMarginUsd")} onToggle={() => toggle("entryMarginUsd")} onChange={(v) => setDraft((d) => ({ ...d, entryMarginUsd: v }))} muted="Geldt vanaf volgende nieuwe cycle" /><Input label="Minimum leverage" value={draft.minimumLeverage} suffix="x" enabled={enabledFields.has("minimumLeverage")} onToggle={() => toggle("minimumLeverage")} onChange={(v) => setDraft((d) => ({ ...d, minimumLeverage: v }))} muted="Geldt vanaf volgende nieuwe cycle" /><Input label="SHORT start-multiplier" value={draft.shortStartMultiplier} suffix="x" enabled={enabledFields.has("shortStartMultiplier")} onToggle={() => toggle("shortStartMultiplier")} onChange={(v) => setDraft((d) => ({ ...d, shortStartMultiplier: v }))} muted="Alleen nieuwe asymmetrische cycle" /></section>
        {(["LONG", "SHORT"] as Side[]).map((side) => { const p = side === "LONG" ? "long" : "short"; const maxKey = side === "LONG" ? "maxDcaLong" : "maxDcaShort"; return <section key={side} style={{ display: "grid", gap: 7, padding: 11, border: side === "LONG" ? "1px solid rgba(88,240,174,.25)" : "1px solid rgba(255,104,130,.25)", borderRadius: 13 }}><b style={{ color: side === "LONG" ? "#66efb0" : "#ff8ba0" }}>{side}</b><Input label={`DCA-bedrag ${side}`} value={draft[side].dcaAmount} suffix="USDT" enabled={enabledFields.has(`${p}DcaMarginUsd` as FieldKey)} onToggle={() => toggle(`${p}DcaMarginUsd` as FieldKey)} onChange={(v) => updateSide(side, "dcaAmount", v)} /><Input label={`DCA-afstand ${side}`} value={draft[side].dcaDistance} suffix="%" enabled={enabledFields.has(`${p}DcaDistance` as FieldKey)} onToggle={() => toggle(`${p}DcaDistance` as FieldKey)} onChange={(v) => updateSide(side, "dcaDistance", v)} /><Input label={`Max DCA ${side}`} value={draft[side].maxDca} suffix="" enabled={enabledFields.has(maxKey as FieldKey)} onToggle={() => toggle(maxKey as FieldKey)} onChange={(v) => updateSide(side, "maxDca", v)} /><Input label={`Take Profit ${side}`} value={draft[side].takeProfit} suffix="%" enabled={enabledFields.has(`${p}TakeProfitValue` as FieldKey)} onToggle={() => toggle(`${p}TakeProfitValue` as FieldKey)} onChange={(v) => updateSide(side, "takeProfit", v)} muted={tpMuted || undefined} /></section>; })}
      </div>
      <p style={{ color: "#87958e", fontSize: 12, lineHeight: 1.5 }}>Max DCA, DCA-afstand, DCA-bedrag en TP worden vanaf de actuele actieve state toegepast. Bestaande DCA-count, qty, avg entry, fills en cycle-baseline worden niet gereset.</p>
      {message && <p role="status" style={{ padding: 10, borderRadius: 10, background: "rgba(88,240,174,.07)", color: /mislukt|ongeldig|moet/i.test(message) ? "#ff8d9e" : "#8cf5bd", fontSize: 13 }}>{message}</p>}
      <footer style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 9 }}><button type="button" disabled={busy} onClick={() => { setCustomEnabled(false); setEnabledFields(new Set()); }} style={{ minHeight: 49, borderRadius: 12, border: "1px solid #39453f", background: "#101613", color: "#d4dbd7", fontWeight: 850 }}>Gebruik algemene instellingen</button><button type="button" disabled={busy} onClick={save} style={{ minHeight: 49, borderRadius: 12, border: "1px solid #58f0ae", background: "#0d3928", color: "#8cf5bd", fontWeight: 900 }}>{busy ? "Opslaan…" : "Pair opslaan"}</button></footer>
    </section>
  </div>;
}
