"use client";

import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

const VISUAL_REFERENCE = "file_000000003e34820a9d0c8dc22b84ac47";
const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;
type Timeframe = typeof TIMEFRAMES[number];
type TpMode = "PER_TRADE" | "PORTFOLIO" | "OFF";
type ReleaseFeature = { key?: string; status?: string; beta?: boolean; stable?: boolean; enabled?: boolean; updatedAt?: unknown };
type ReleaseState = { channel?: "BETA" | "STABLE"; features?: Record<string, ReleaseFeature> };

type Props = {
  snapshot: Record<string, unknown> | null;
  serverConfirmed: boolean;
  onConfirmed: (strategy2: Record<string, unknown>) => void;
  onChanged: () => void;
  release: ReleaseState;
};

type Draft = {
  name: string;
  universeTopN: string;
  longSlots: string;
  shortSlots: string;
  minimumLeverage: string;
  maximumLeverage: string;
  manualEnabled: boolean;
  manualSymbols: string;
  bollingerEnabled: boolean;
  directionalBollingerEnabled: boolean;
  bollingerLongTimeframe: Timeframe;
  bollingerShortTimeframe: Timeframe;
  exposureRefillEnabled: boolean;
  exposureRefillLongTimeframe: Timeframe;
  exposureRefillShortTimeframe: Timeframe;
  exposureRefillTriggerPercent: string;
  exposureRefillReleasePercent: string;
  fixedPositionSize: boolean;
  entryMarginLong: string;
  entryMarginShort: string;
  entryNotionalLong: string;
  entryNotionalShort: string;
  longDcaDistance: string;
  shortDcaDistance: string;
  longDcaAmount: string;
  shortDcaAmount: string;
  maxDcaLong: string;
  maxDcaShort: string;
  tpMode: TpMode;
  longTp: string;
  shortTp: string;
  portfolioTpValue: string;
  portfolioTpInputMode: "PERCENT" | "USD";
  shortRequiresLongEnabled: boolean;
  stopLossEnabled: boolean;
  stopLossMode: "PERCENT" | "USD";
  stopLossLong: string;
  stopLossShort: string;
  smartRescueEnabled: boolean;
  smartRescueRange: string;
  smartRescueCount: string;
  smartRescueGrowth: string;
  smartRescueRecovery: string;
};

const n = (value: unknown, fallback = 0) => {
  const number = Number(String(value ?? "").replace(",", "."));
  return Number.isFinite(number) ? number : fallback;
};
const pctText = (value: unknown, fallback: number) => String(n(value, fallback) * 100);
const textValue = (value: unknown, fallback: number) => String(Number.isFinite(Number(value)) ? Number(value) : fallback);
const tf = (value: unknown, fallback: Timeframe): Timeframe => TIMEFRAMES.includes(String(value) as Timeframe) ? String(value) as Timeframe : fallback;
const money = (value: number) => value.toLocaleString("nl-NL", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });

function normalizeDraft(settings: Record<string, unknown>): Draft {
  const legacyEntry = n(settings.entryMarginUsd, 5);
  const legacyDistance = n(settings.dcaDistance, .003);
  const legacyDca = n(settings.dcaMarginUsd, 2);
  const legacyMax = n(settings.maxDca, 3);
  const legacyTp = n(settings.takeProfit, .015);
  const tpMode = String(settings.takeProfitMode || (settings.takeProfitEnabled === false ? "OFF" : "PER_TRADE")).toUpperCase();
  const manualRows = Array.isArray(settings.manualSymbols) ? settings.manualSymbols : [];
  const manualText = manualRows.flatMap((row) => {
    if (!row || typeof row !== "object") return [];
    const item = row as Record<string, unknown>;
    const symbol = String(item.symbol || "").trim().toUpperCase();
    const side = String(item.side || "LONG").trim().toUpperCase();
    return symbol ? [symbol + ":" + (side === "SHORT" ? "SHORT" : "LONG")] : [];
  }).join(", ");
  return {
    name: String(settings.name || "Aster Multi DCA"),
    universeTopN: textValue(settings.universeTopN, 30),
    longSlots: textValue(settings.longSlots, 20),
    shortSlots: textValue(settings.shortSlots, 10),
    minimumLeverage: textValue(settings.minimumLeverage, 50),
    maximumLeverage: settings.maximumLeverage === null || settings.maximumLeverage === undefined ? "" : textValue(settings.maximumLeverage, 0),
    manualEnabled: settings.manualSymbolSelectionEnabled === true,
    manualSymbols: manualText,
    bollingerEnabled: settings.bollingerEntryFilter15mEnabled === true,
    directionalBollingerEnabled: settings.directionalBollingerEnabled === true,
    bollingerLongTimeframe: tf(settings.bollingerLongTimeframe ?? settings.bollingerEntryFilterTimeframe, "15m"),
    bollingerShortTimeframe: tf(settings.bollingerShortTimeframe ?? settings.bollingerEntryFilterTimeframe, "15m"),
    exposureRefillEnabled: settings.exposureRefillEnabled === true,
    exposureRefillLongTimeframe: tf(settings.exposureRefillLongTimeframe, "1m"),
    exposureRefillShortTimeframe: tf(settings.exposureRefillShortTimeframe, "1m"),
    exposureRefillTriggerPercent: textValue(settings.exposureRefillTriggerPercent, 20),
    exposureRefillReleasePercent: textValue(settings.exposureRefillReleasePercent, 8),
    fixedPositionSize: String(settings.entrySizingMode || "margin").toLowerCase() === "notional",
    entryMarginLong: textValue(settings.entryMarginLongUsd ?? settings.entryMarginLong ?? legacyEntry, legacyEntry),
    entryMarginShort: textValue(settings.entryMarginShortUsd ?? settings.entryMarginShort ?? legacyEntry, legacyEntry),
    entryNotionalLong: textValue(settings.entryNotionalLongUsd ?? settings.entryNotionalLong ?? settings.entryNotionalUsd, 0),
    entryNotionalShort: textValue(settings.entryNotionalShortUsd ?? settings.entryNotionalShort ?? settings.entryNotionalUsd, 0),
    longDcaDistance: pctText(settings.longDcaDistance ?? legacyDistance, legacyDistance),
    shortDcaDistance: pctText(settings.shortDcaDistance ?? legacyDistance, legacyDistance),
    longDcaAmount: textValue(settings.longDcaMarginUsd ?? settings.longDcaAmount ?? legacyDca, legacyDca),
    shortDcaAmount: textValue(settings.shortDcaMarginUsd ?? settings.shortDcaAmount ?? legacyDca, legacyDca),
    maxDcaLong: textValue(settings.maxDcaLong ?? settings.longMaxDca ?? legacyMax, legacyMax),
    maxDcaShort: textValue(settings.maxDcaShort ?? settings.shortMaxDca ?? legacyMax, legacyMax),
    tpMode: tpMode === "PORTFOLIO" ? "PORTFOLIO" : tpMode === "OFF" ? "OFF" : "PER_TRADE",
    longTp: pctText(settings.longTakeProfitValue ?? settings.takeProfitLong ?? legacyTp, legacyTp),
    shortTp: pctText(settings.shortTakeProfitValue ?? settings.takeProfitShort ?? legacyTp, legacyTp),
    portfolioTpValue: textValue(settings.portfolioTpValue ?? settings.portfolioTpPercent, 20),
    portfolioTpInputMode: String(settings.portfolioTpInputMode || "PERCENT").toUpperCase() === "USD" ? "USD" : "PERCENT",
    shortRequiresLongEnabled: settings.shortRequiresLongEnabled === true,
    stopLossEnabled: settings.stopLossEnabled === true,
    stopLossMode: String(settings.stopLossMode || "PERCENT").toUpperCase() === "USD" ? "USD" : "PERCENT",
    stopLossLong: textValue(settings.stopLossLong, 5),
    stopLossShort: textValue(settings.stopLossShort, 5),
    smartRescueEnabled: settings.smartRescueEnabled === true,
    smartRescueRange: textValue(settings.smartRescueRangePercent, 10),
    smartRescueCount: textValue(settings.smartRescueDcaCount, 10),
    smartRescueGrowth: textValue(settings.smartRescueOrderGrowthMultiplier, 1.35),
    smartRescueRecovery: textValue(settings.smartRescueTrailingRecoveryPercent, .3),
  };
}

function parseManual(value: string) {
  const seen = new Set<string>();
  return value.split(",").flatMap((part) => {
    const [rawSymbol, rawSide] = part.trim().toUpperCase().split(":");
    const symbol = rawSymbol?.trim();
    const side = rawSide === "SHORT" ? "SHORT" : "LONG";
    const key = symbol + "|" + side;
    if (!symbol || seen.has(key)) return [];
    seen.add(key);
    return [{ symbol, side }];
  });
}

function Field({ label, value, onChange, suffix, type = "number", min, step = "any", disabled = false }: {
  label: string; value: string; onChange: (value: string) => void; suffix?: string; type?: "number" | "text"; min?: number; step?: string; disabled?: boolean;
}) {
  return <label className="v2-field"><span>{label}</span><span className="v2-input"><input disabled={disabled} type={type} min={min} step={step} value={value} onChange={(e) => onChange(e.target.value)} />{suffix && <em>{suffix}</em>}</span></label>;
}

function Toggle({ label, description, checked, onChange, disabled = false }: { label: string; description?: string; checked: boolean; onChange: (value: boolean) => void; disabled?: boolean }) {
  return <label className={"v2-toggle " + (checked ? "on" : "") + (disabled ? " disabled" : "")}><span><b>{label}</b>{description && <small>{description}</small>}</span><input type="checkbox" disabled={disabled} checked={checked} onChange={(e) => onChange(e.target.checked)} /><i /></label>;
}

function TimeframeSelect({ label, value, onChange, disabled = false }: { label: string; value: Timeframe; onChange: (value: Timeframe) => void; disabled?: boolean }) {
  return <label className="v2-field"><span>{label}</span><select disabled={disabled} value={value} onChange={(e) => onChange(e.target.value as Timeframe)}>{TIMEFRAMES.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>;
}

const STEP_LABELS = [
  ["markt", "Markt"], ["posities", "Posities"], ["instap", "Instap"], ["grootte", "Grootte"],
  ["dca", "DCA"], ["winst", "Winst"], ["bescherming", "Bescherming"], ["controle", "Controle"],
] as const;

export function AsterBotConfiguratorV2({ snapshot, serverConfirmed, onConfirmed, onChanged, release }: Props) {
  const strategy2 = snapshot?.strategy2 && typeof snapshot.strategy2 === "object" ? snapshot.strategy2 as Record<string, unknown> : {};
  const persisted = strategy2.settings && typeof strategy2.settings === "object" ? strategy2.settings as Record<string, unknown> : {};
  const enabled = strategy2.enabled === true;
  const report = strategy2.multiBb && typeof strategy2.multiBb === "object" ? strategy2.multiBb as Record<string, unknown> :
    strategy2.multiBbReport && typeof strategy2.multiBbReport === "object" ? strategy2.multiBbReport as Record<string, unknown> : {};
  const [draft, setDraft] = useState<Draft>(() => normalizeDraft(persisted));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [activeStep, setActiveStep] = useState("markt");
  const [releases, setReleases] = useState<ReleaseState>(release);

  useEffect(() => {
    if (!dirty) setDraft(normalizeDraft(persisted));
  }, [JSON.stringify(persisted), dirty]);

  useEffect(() => {
    const observers: IntersectionObserver[] = [];
    for (const [id] of STEP_LABELS) {
      const node = document.getElementById("v2-step-" + id);
      if (!node) continue;
      const observer = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setActiveStep(id);
      }, { rootMargin: "-22% 0px -64% 0px", threshold: [0, .1, .5] });
      observer.observe(node); observers.push(observer);
    }
    return () => observers.forEach((observer) => observer.disconnect());
  }, []);

  const ownerBeta = releases.channel === "BETA";
  const feature = (key: string) => releases.features?.[key] ?? release.features?.[key] ?? {};
  const directionalAvailable = feature("directional_bollinger").enabled === true;
  const exposureAvailable = feature("exposure_refill").enabled === true;
  const priceZonesAvailable = feature("price_zones").enabled === true;

  const update = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setDirty(true); setMessage("");
  };

  const totals = useMemo(() => {
    const longSlots = Math.max(0, Math.round(n(draft.longSlots)));
    const shortSlots = Math.max(0, Math.round(n(draft.shortSlots)));
    const totalSlots = longSlots + shortSlots;
    const startMargin = draft.fixedPositionSize
      ? (n(draft.entryNotionalLong) * longSlots + n(draft.entryNotionalShort) * shortSlots) / Math.max(1, n(draft.minimumLeverage, 1))
      : n(draft.entryMarginLong) * longSlots + n(draft.entryMarginShort) * shortSlots;
    const dcaCapacity = n(draft.longDcaAmount) * Math.max(0, Math.round(n(draft.maxDcaLong))) * longSlots +
      n(draft.shortDcaAmount) * Math.max(0, Math.round(n(draft.maxDcaShort))) * shortSlots;
    return { longSlots, shortSlots, totalSlots, startMargin, dcaCapacity, theoretical: startMargin + dcaCapacity };
  }, [draft]);

  const available = n(snapshot?.availableBalance ?? snapshot?.availableToTrade ?? snapshot?.available, 0);
  const equity = n(snapshot?.equity ?? snapshot?.portfolioValue, 0);
  const netExposure = n(report.netExposureNotional ?? report.netExposure, 0);
  const exposureSide = String(report.exposureRefillSide || "");
  const imbalance = n(report.exposureImbalancePercent, 0);
  const liveLongRaw = Number(report.activeLong);
  const liveShortRaw = Number(report.activeShort);
  const activeLong = Number.isFinite(liveLongRaw) ? Math.max(0, Math.round(liveLongRaw)) : null;
  const activeShort = Number.isFinite(liveShortRaw) ? Math.max(0, Math.round(liveShortRaw)) : null;
  const activeTotal = activeLong !== null && activeShort !== null ? activeLong + activeShort : null;
  const slotFill = (active: number | null, capacity: number) => active === null
    ? 0
    : capacity <= 0
      ? (active > 0 ? 100 : 0)
      : Math.min(100, Math.max(0, active / capacity * 100));

  function buildSettings() {
    if (totals.totalSlots < 1 || totals.totalSlots > 100) throw new Error("LONG + SHORT moet tussen 1 en 100 posities liggen.");
    const minLev = Math.max(1, Math.round(n(draft.minimumLeverage)));
    const maxLev = draft.maximumLeverage.trim() ? Math.max(1, Math.round(n(draft.maximumLeverage))) : null;
    if (maxLev !== null && maxLev < minLev) throw new Error("Maximum leverage moet gelijk aan of hoger zijn dan minimum leverage.");
    if (n(draft.longDcaDistance) <= 0 || n(draft.shortDcaDistance) <= 0 || n(draft.longDcaDistance) > 50 || n(draft.shortDcaDistance) > 50) throw new Error("DCA-afstand moet tussen 0 en 50% liggen.");
    if (n(draft.exposureRefillReleasePercent) < 0 || n(draft.exposureRefillReleasePercent) >= n(draft.exposureRefillTriggerPercent)) throw new Error("Exposure stopdrempel moet lager zijn dan de startdrempel.");
    const sizing = draft.fixedPositionSize ? {
      entrySizingMode: "notional",
      entryNotionalUsd: n(draft.entryNotionalLong),
      entryNotionalLongUsd: n(draft.entryNotionalLong),
      entryNotionalShortUsd: n(draft.entryNotionalShort),
      entryNotionalLong: n(draft.entryNotionalLong),
      entryNotionalShort: n(draft.entryNotionalShort),
    } : { entrySizingMode: "margin" };
    return {
      ...persisted,
      engine: "multi_bb_v1",
      strategyKind: "multi_bb_v1",
      name: draft.name,
      universeTopN: Math.max(1, Math.round(n(draft.universeTopN))),
      maximumPositions: totals.totalSlots,
      longSlots: totals.longSlots,
      shortSlots: totals.shortSlots,
      minimumLeverage: minLev,
      maximumLeverage: maxLev,
      manualSymbolSelectionEnabled: draft.manualEnabled,
      manualSymbols: draft.manualEnabled ? parseManual(draft.manualSymbols) : [],
      bollingerEntryFilter15mEnabled: draft.bollingerEnabled,
      bollingerEntryFilterTimeframe: draft.bollingerLongTimeframe,
      ...(directionalAvailable ? {
        directionalBollingerEnabled: draft.directionalBollingerEnabled,
        bollingerLongTimeframe: draft.bollingerLongTimeframe,
        bollingerShortTimeframe: draft.bollingerShortTimeframe,
      } : {}),
      ...(exposureAvailable ? {
        exposureRefillEnabled: draft.exposureRefillEnabled,
        exposureRefillLongTimeframe: draft.exposureRefillLongTimeframe,
        exposureRefillShortTimeframe: draft.exposureRefillShortTimeframe,
        exposureRefillTriggerPercent: n(draft.exposureRefillTriggerPercent),
        exposureRefillReleasePercent: n(draft.exposureRefillReleasePercent),
      } : {}),
      ...sizing,
      entryMarginUsd: n(draft.entryMarginLong),
      entryMarginLongUsd: n(draft.entryMarginLong),
      entryMarginShortUsd: n(draft.entryMarginShort),
      entryMarginLong: n(draft.entryMarginLong),
      entryMarginShort: n(draft.entryMarginShort),
      dcaDistance: n(draft.longDcaDistance) / 100,
      longDcaDistance: n(draft.longDcaDistance) / 100,
      shortDcaDistance: n(draft.shortDcaDistance) / 100,
      dcaMarginUsd: n(draft.longDcaAmount),
      longDcaMarginUsd: n(draft.longDcaAmount),
      shortDcaMarginUsd: n(draft.shortDcaAmount),
      longDcaAmount: n(draft.longDcaAmount),
      shortDcaAmount: n(draft.shortDcaAmount),
      maxDca: Math.max(0, Math.round(n(draft.maxDcaLong))),
      maxDcaLong: Math.max(0, Math.round(n(draft.maxDcaLong))),
      maxDcaShort: Math.max(0, Math.round(n(draft.maxDcaShort))),
      longMaxDca: Math.max(0, Math.round(n(draft.maxDcaLong))),
      shortMaxDca: Math.max(0, Math.round(n(draft.maxDcaShort))),
      takeProfitMode: draft.tpMode,
      takeProfitEnabled: draft.tpMode !== "OFF",
      takeProfit: n(draft.longTp) / 100,
      longTakeProfitValue: n(draft.longTp) / 100,
      shortTakeProfitValue: n(draft.shortTp) / 100,
      takeProfitLong: n(draft.longTp) / 100,
      takeProfitShort: n(draft.shortTp) / 100,
      portfolioTpValue: n(draft.portfolioTpValue),
      portfolioTpInputMode: draft.portfolioTpInputMode,
      shortRequiresLongEnabled: draft.shortRequiresLongEnabled,
      stopLossEnabled: draft.stopLossEnabled,
      stopLossMode: draft.stopLossMode,
      stopLossLong: n(draft.stopLossLong),
      stopLossShort: n(draft.stopLossShort),
      smartRescueEnabled: draft.smartRescueEnabled,
      smartRescueRangePercent: n(draft.smartRescueRange),
      smartRescueDcaCount: Math.max(1, Math.round(n(draft.smartRescueCount))),
      smartRescueOrderGrowthMultiplier: Math.max(1, n(draft.smartRescueGrowth)),
      smartRescueTrailingRecoveryPercent: Math.max(0, n(draft.smartRescueRecovery)),
      entryMode: "immediate_fill",
      marginMode: "cross",
      autoRestart: true,
    };
  }

  async function save() {
    setBusy(true); setMessage("");
    try {
      const settings = buildSettings();
      const result = await authenticatedRequest("/api/exchanges/aster/strategy2/settings", { method: "PUT", body: JSON.stringify({ settings }) }) as Record<string, unknown>;
      const confirmed = result.strategy2 && typeof result.strategy2 === "object" ? result.strategy2 as Record<string, unknown> : null;
      if (!confirmed) throw new Error("Server heeft de instellingen niet bevestigd.");
      onConfirmed(confirmed); setDirty(false);
      setMessage("BETA-instellingen server-side opgeslagen. Bestaande posities, DCA-state en cycle-state zijn behouden.");
      await Promise.resolve(onChanged());
      return settings;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Opslaan mislukt.");
      throw error;
    } finally { setBusy(false); }
  }

  async function bottomAction() {
    setBusy(true); setMessage("");
    try {
      const settings = buildSettings();
      if (enabled) {
        const result = await authenticatedRequest("/api/exchanges/aster/strategy2/settings", { method: "PUT", body: JSON.stringify({ settings }) }) as Record<string, unknown>;
        const confirmed = result.strategy2 && typeof result.strategy2 === "object" ? result.strategy2 as Record<string, unknown> : null;
        if (confirmed) onConfirmed(confirmed);
        setDirty(false); setMessage("Instellingen opgeslagen; actieve bot-state is behouden.");
      } else {
        const result = await authenticatedRequest("/api/exchanges/aster/strategy2/start", { method: "POST", body: JSON.stringify({ confirm: true, settings }) }) as Record<string, unknown>;
        const confirmed = result.strategy2 && typeof result.strategy2 === "object" ? result.strategy2 as Record<string, unknown> : null;
        if (confirmed) onConfirmed(confirmed);
        setDirty(false); setMessage(result.started === true ? "BETA-bot gestart met de nieuwe configuratie." : "Start nog niet server-side bevestigd.");
      }
      await Promise.resolve(onChanged());
    } catch (error) { setMessage(error instanceof Error ? error.message : "Actie mislukt."); }
    finally { setBusy(false); }
  }

  async function stopBot() {
    setBusy(true); setMessage("");
    try {
      const result = await authenticatedRequest("/api/exchanges/aster/strategy2/stop", { method: "POST", body: JSON.stringify({ confirm: true }) }) as Record<string, unknown>;
      const confirmed = result.strategy2 && typeof result.strategy2 === "object" ? result.strategy2 as Record<string, unknown> : null;
      if (confirmed) onConfirmed(confirmed);
      setMessage("Bot-stop server-side verwerkt. Open posities zijn niet door deze UI-wijziging gesloten.");
      await Promise.resolve(onChanged());
    } catch (error) { setMessage(error instanceof Error ? error.message : "Stoppen mislukt."); }
    finally { setBusy(false); }
  }

  async function refreshReleases() {
    try { setReleases(await authenticatedRequest("/api/admin/releases", { cache: "no-store" }) as ReleaseState); } catch { /* owner-only panel remains non-blocking */ }
  }

  async function changeRelease(key: string, patch: { status: string; beta?: boolean; stable?: boolean; confirm?: boolean }) {
    setBusy(true); setMessage("");
    try {
      await authenticatedRequest("/api/admin/releases/" + encodeURIComponent(key), { method: "PUT", body: JSON.stringify(patch) });
      await refreshReleases();
      setMessage("Release-status bijgewerkt. Alleen het gekozen blok is aangepast.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Releasewijziging mislukt."); }
    finally { setBusy(false); }
  }

  const scrollTo = (id: string) => document.getElementById("v2-step-" + id)?.scrollIntoView({ behavior: "smooth", block: "start" });

  return <article id="bot-configurator-v2" data-reference={VISUAL_REFERENCE}>
    <header className="v2-hero">
      <div>{ownerBeta && <span className="v2-beta">BETA · alleen zichtbaar voor jou</span>}<h2>Botconfigurator V2</h2><p>{ownerBeta ? "Bouw en test nieuwe blokken op jouw account. STABLE-gebruikers blijven op hun vrijgegeven logica." : "Bouw je Aster-bot stap voor stap met alleen vrijgegeven functies."}</p></div>
      <div className={"v2-live " + (enabled ? "on" : "")}><i /><span><small>Aster live bot</small><b>{enabled ? "AAN" : "UIT"}</b></span>{enabled && <button type="button" disabled={busy} onClick={stopBot}>Uitschakelen</button>}</div>
    </header>

    <nav className="v2-stepnav" aria-label="Configuratiestappen">{STEP_LABELS.map(([id, label], index) => <button key={id} type="button" className={activeStep === id ? "active" : ""} onClick={() => scrollTo(id)}><b>{index + 1}</b><span>{label}</span></button>)}</nav>

    <section className="v2-step" id="v2-step-markt"><StepHead number="1" title="Markt" subtitle="Waar mag de bot handelen?" />
      <div className="v2-grid cols2">
        <Field label="Top-N volume" value={draft.universeTopN} onChange={(v) => update("universeTopN", v)} min={1} />
        <Field label="Botnaam" type="text" value={draft.name} onChange={(v) => update("name", v)} />
        <Field label="Minimum leverage" value={draft.minimumLeverage} onChange={(v) => update("minimumLeverage", v)} suffix="×" min={1} />
        <Field label="Maximum leverage" value={draft.maximumLeverage} onChange={(v) => update("maximumLeverage", v)} suffix="×" min={1} />
      </div>
      <Toggle label="Zelf munten kiezen" description="Uit = automatische Top-N. Aan = alleen de hieronder opgegeven Aster USDT perpetuals." checked={draft.manualEnabled} onChange={(v) => update("manualEnabled", v)} />
      {draft.manualEnabled && <Field label="Munten · SYMBOL:LONG of SYMBOL:SHORT, komma-gescheiden" type="text" value={draft.manualSymbols} onChange={(v) => update("manualSymbols", v)} />}
    </section>

    <section className="v2-step" id="v2-step-posities"><StepHead number="2" title="Posities" subtitle="Hoe wil je je portfolio verdelen?" />
      <div className="v2-slot-visual" aria-label="Actieve posities ten opzichte van ingestelde stoelcapaciteit">
        <div className="long"><span>LONG</span><i title={activeLong === null ? "Live bezetting wordt geladen" : activeLong + " van " + totals.longSlots + " LONG-stoelen bezet"}><u style={{ width: slotFill(activeLong, totals.longSlots) + "%" }} /></i><b>{activeLong === null ? "—/" + totals.longSlots : activeLong + "/" + totals.longSlots}</b></div>
        <div className="short"><span>SHORT</span><i title={activeShort === null ? "Live bezetting wordt geladen" : activeShort + " van " + totals.shortSlots + " SHORT-stoelen bezet"}><u style={{ width: slotFill(activeShort, totals.shortSlots) + "%" }} /></i><b>{activeShort === null ? "—/" + totals.shortSlots : activeShort + "/" + totals.shortSlots}</b></div>
        <div className="total"><span>TOTAAL</span><strong>{activeTotal === null ? "—/" + totals.totalSlots : activeTotal + "/" + totals.totalSlots}</strong></div>
      </div>
      <small className="v2-note">Bezet / capaciteit. Vrije stoelen worden pas gevuld na een geldige instap.</small>
      <div className="v2-grid cols2"><Field label="LONG slots" value={draft.longSlots} onChange={(v) => update("longSlots", v)} /><Field label="SHORT slots" value={draft.shortSlots} onChange={(v) => update("shortSlots", v)} /></div>
      <small className="v2-note">LONG wijzigen laat SHORT staan; SHORT wijzigen laat LONG staan. Totaal wordt automatisch berekend.</small>
    </section>

    <section className="v2-step" id="v2-step-instap"><StepHead number="3" title="Instaplogica" subtitle="Wanneer mag een nieuwe positie openen?" />
      <Toggle label="Bollinger instapfilter" description="Filtert alleen nieuwe initial entries; DCA blijft volledig apart." checked={draft.bollingerEnabled} onChange={(v) => update("bollingerEnabled", v)} />
      <div className="v2-sidegrid">
        <article className="v2-side long"><b>LONG</b><TimeframeSelect label="Normale instap" value={draft.bollingerLongTimeframe} onChange={(v) => update("bollingerLongTimeframe", v)} disabled={!draft.bollingerEnabled} /><TimeframeSelect label="Snelle refill" value={draft.exposureRefillLongTimeframe} onChange={(v) => update("exposureRefillLongTimeframe", v)} disabled={!draft.bollingerEnabled || !exposureAvailable} /></article>
        <article className="v2-side short"><b>SHORT</b><TimeframeSelect label="Normale instap" value={draft.bollingerShortTimeframe} onChange={(v) => update("bollingerShortTimeframe", v)} disabled={!draft.bollingerEnabled || !directionalAvailable} /><TimeframeSelect label="Snelle refill" value={draft.exposureRefillShortTimeframe} onChange={(v) => update("exposureRefillShortTimeframe", v)} disabled={!draft.bollingerEnabled || !exposureAvailable} /></article>
      </div>
      <Toggle label="LONG en SHORT apart" description={directionalAvailable ? "Iedere richting mag zijn eigen normale Bollinger-timeframe gebruiken." : "Dit blok is nog niet vrijgegeven voor dit releasekanaal."} checked={draft.directionalBollingerEnabled} onChange={(v) => update("directionalBollingerEnabled", v)} disabled={!directionalAvailable} />
      <Toggle label="Automatische exposure-refill" description={exposureAvailable ? "Bij scheve netto exposure krijgt alleen de ontbrekende kant tijdelijk de snelle timeframe." : "Nog niet vrijgegeven."} checked={draft.exposureRefillEnabled} onChange={(v) => update("exposureRefillEnabled", v)} disabled={!exposureAvailable} />
      {exposureAvailable && draft.exposureRefillEnabled && <div className="v2-grid cols2"><Field label="Snelle refill vanaf" value={draft.exposureRefillTriggerPercent} onChange={(v) => update("exposureRefillTriggerPercent", v)} suffix="% onbalans" /><Field label="Terug naar normaal onder" value={draft.exposureRefillReleasePercent} onChange={(v) => update("exposureRefillReleasePercent", v)} suffix="% onbalans" /></div>}
      <div className="v2-runtime-strip"><span><small>Netto exposure</small><b className={netExposure < 0 ? "short" : netExposure > 0 ? "long" : ""}>{money(netExposure)}</b></span><span><small>Onbalans</small><b>{imbalance.toFixed(1)}%</b></span><span><small>Snelle refill</small><b>{exposureSide || "niet actief"}</b></span></div>
    </section>

    <section className="v2-step" id="v2-step-grootte"><StepHead number="4" title="Positiegrootte" subtitle="Hoe groot start iedere positie?" />
      <Toggle label="Vaste positieomvang" description="Uit = bedragen zijn margin. Aan = vaste notional in USDT; bestaande marginvelden blijven bewaard." checked={draft.fixedPositionSize} onChange={(v) => update("fixedPositionSize", v)} />
      <div className="v2-sidegrid"><article className="v2-side long"><b>LONG</b><Field label="Instap margin" value={draft.entryMarginLong} onChange={(v) => update("entryMarginLong", v)} suffix="USDT" />{draft.fixedPositionSize && <Field label="Vaste positie" value={draft.entryNotionalLong} onChange={(v) => update("entryNotionalLong", v)} suffix="USDT" />}</article><article className="v2-side short"><b>SHORT</b><Field label="Instap margin" value={draft.entryMarginShort} onChange={(v) => update("entryMarginShort", v)} suffix="USDT" />{draft.fixedPositionSize && <Field label="Vaste positie" value={draft.entryNotionalShort} onChange={(v) => update("entryNotionalShort", v)} suffix="USDT" />}</article></div>
    </section>

    <section className="v2-step" id="v2-step-dca"><StepHead number="5" title="DCA" subtitle="Wat gebeurt er als een positie tegen je ingaat?" />
      <div className="v2-sidegrid">
        <article className="v2-side long"><b>LONG</b><Field label="DCA-afstand" value={draft.longDcaDistance} onChange={(v) => update("longDcaDistance", v)} suffix="%" /><Field label="DCA-bedrag" value={draft.longDcaAmount} onChange={(v) => update("longDcaAmount", v)} suffix="USDT" /><Field label="Max DCA" value={draft.maxDcaLong} onChange={(v) => update("maxDcaLong", v)} /></article>
        <article className="v2-side short"><b>SHORT</b><Field label="DCA-afstand" value={draft.shortDcaDistance} onChange={(v) => update("shortDcaDistance", v)} suffix="%" /><Field label="DCA-bedrag" value={draft.shortDcaAmount} onChange={(v) => update("shortDcaAmount", v)} suffix="USDT" /><Field label="Max DCA" value={draft.maxDcaShort} onChange={(v) => update("maxDcaShort", v)} /></article>
      </div>
      <details className="v2-advanced"><summary>Smart Rescue DCA</summary><Toggle label="Smart Rescue" description="Bestaande functie; instellingen blijven accountgebonden." checked={draft.smartRescueEnabled} onChange={(v) => update("smartRescueEnabled", v)} />{draft.smartRescueEnabled && <div className="v2-grid cols2"><Field label="Rescue bereik" value={draft.smartRescueRange} onChange={(v) => update("smartRescueRange", v)} suffix="%" /><Field label="Aantal DCA's" value={draft.smartRescueCount} onChange={(v) => update("smartRescueCount", v)} /><Field label="Ordergroei" value={draft.smartRescueGrowth} onChange={(v) => update("smartRescueGrowth", v)} suffix="×" /><Field label="Koop na herstel" value={draft.smartRescueRecovery} onChange={(v) => update("smartRescueRecovery", v)} suffix="%" /></div>}</details>
    </section>

    <section className="v2-step" id="v2-step-winst"><StepHead number="6" title="Winst nemen" subtitle="Wanneer wordt winst gecasht?" />
      <div className="v2-tabs">{(["PER_TRADE", "PORTFOLIO", "OFF"] as TpMode[]).map((mode) => <button key={mode} type="button" className={draft.tpMode === mode ? "active" : ""} onClick={() => update("tpMode", mode)}>{mode === "PER_TRADE" ? "Per trade" : mode === "PORTFOLIO" ? "Portfolio" : "Uit"}</button>)}</div>
      <div className="v2-sidegrid"><article className="v2-side long"><b>LONG</b><Field label="Take Profit" value={draft.longTp} onChange={(v) => update("longTp", v)} suffix="%" disabled={draft.tpMode === "OFF"} /></article><article className="v2-side short"><b>SHORT</b><Field label="Take Profit" value={draft.shortTp} onChange={(v) => update("shortTp", v)} suffix="%" disabled={draft.tpMode === "OFF"} /></article></div>
      {draft.tpMode === "PORTFOLIO" && <div className="v2-grid cols2"><Field label="Portfolio TP" value={draft.portfolioTpValue} onChange={(v) => update("portfolioTpValue", v)} suffix={draft.portfolioTpInputMode === "USD" ? "$" : "%"} /><label className="v2-field"><span>Invoermodus</span><select value={draft.portfolioTpInputMode} onChange={(e) => update("portfolioTpInputMode", e.target.value as "PERCENT" | "USD")}><option value="PERCENT">%</option><option value="USD">$</option></select></label></div>}
    </section>

    <section className="v2-step" id="v2-step-bescherming"><StepHead number="7" title="Bescherming & exposure" subtitle="Hoe bewaakt de bot je portfolio?" />
      <Toggle label="SHORT alleen met LONG" description="LONG mag zelfstandig openen; nieuwe SHORT alleen wanneer dezelfde pair al LONG heeft." checked={draft.shortRequiresLongEnabled} onChange={(v) => update("shortRequiresLongEnabled", v)} />
      <Toggle label="Stoploss" description="Bestaande server-side reduce-only bescherming." checked={draft.stopLossEnabled} onChange={(v) => update("stopLossEnabled", v)} />
      {draft.stopLossEnabled && <div className="v2-grid cols2"><Field label="Stoploss LONG" value={draft.stopLossLong} onChange={(v) => update("stopLossLong", v)} suffix={draft.stopLossMode === "USD" ? "$" : "%"} /><Field label="Stoploss SHORT" value={draft.stopLossShort} onChange={(v) => update("stopLossShort", v)} suffix={draft.stopLossMode === "USD" ? "$" : "%"} /></div>}
      <details className="v2-advanced"><summary>Geavanceerde instellingen</summary><p>Exposure-refill verandert uitsluitend de timeframe voor een toegestane nieuwe initial entry. DCA, TP, bestaande posities en zone-eigenaarschap blijven gescheiden.</p><div className="v2-feature-note"><b>Price zones / soldaten</b><span>{priceZonesAvailable ? "BETA actief" : "IN BOUW · nog niet functioneel geactiveerd"}</span></div></details>
    </section>

    <section className="v2-step" id="v2-step-controle"><StepHead number="8" title="Controle & samenvatting" subtitle="Controleer wat je bot gaat doen vóór opslaan of activeren." />
      <div className="v2-summary">
        <Summary label="Markten" value={"Top " + Math.max(1, Math.round(n(draft.universeTopN)))} />
        <Summary label="Posities" value={totals.longSlots + " LONG · " + totals.shortSlots + " SHORT · " + totals.totalSlots + " totaal"} />
        <Summary label="Instap" value={"LONG " + draft.bollingerLongTimeframe + " · SHORT " + draft.bollingerShortTimeframe} />
        <Summary label="Exposure-refill" value={draft.exposureRefillEnabled && exposureAvailable ? "LONG " + draft.exposureRefillLongTimeframe + " · SHORT " + draft.exposureRefillShortTimeframe : "Uit"} />
        <Summary label="LONG" value={"Start $" + draft.entryMarginLong + " · DCA " + draft.longDcaDistance + "% · TP " + draft.longTp + "%"} />
        <Summary label="SHORT" value={"Start $" + draft.entryMarginShort + " · DCA " + draft.shortDcaDistance + "% · TP " + draft.shortTp + "%"} />
      </div>
      <div className="v2-capacity"><span><small>Geschatte startbelasting</small><b>{money(totals.startMargin)}</b></span><span><small>Max ingestelde DCA-capaciteit</small><b>{money(totals.dcaCapacity)}</b></span><span><small>Theoretisch totaal</small><b>{money(totals.theoretical)}</b></span><span><small>Huidig available</small><b>{available > 0 ? money(available) : "—"}</b></span></div>
      {available > 0 && totals.theoretical > available && <p className="v2-warning">Waarschuwing: theoretische volledige ingestelde belasting is hoger dan de huidige available. Dit is een configuratiecheck, geen voorspelling dat alle DCA's tegelijk worden uitgevoerd.</p>}
      <div className="v2-account-strip"><span><small>Equity</small><b>{equity > 0 ? money(equity) : "—"}</b></span><span><small>Serverstatus</small><b>{serverConfirmed ? "Bevestigd" : "Wachten"}</b></span><span><small>Wijzigingen</small><b>{dirty ? "Niet opgeslagen" : "Opgeslagen"}</b></span></div>

      {ownerBeta && <details className="v2-release-center" open>
        <summary>Releasecentrum · alleen BETA-owner</summary>
        <p>Een vinkje/akkoord publiceert niets automatisch. Publiceren en terugtrekken gebeurt per blok.</p>
        <div className="v2-release-list">{Object.entries(releases.features ?? {}).map(([key, row]) => <article key={key}><div><b>{releaseLabel(key)}</b><small>{row.status || "TESTEN"} · BETA {row.beta ? "AAN" : "UIT"} · STABLE {row.stable ? "AAN" : "UIT"}</small></div><span>{row.status !== "AKKOORD" && row.status !== "LIVE" && <button disabled={busy} onClick={() => changeRelease(key, { status: "AKKOORD", beta: true, stable: false })}>✓ Getest en akkoord</button>}{row.status === "AKKOORD" && !row.stable && <button disabled={busy} onClick={() => { if (window.confirm(releaseLabel(key) + " vrijgeven aan alle gebruikers? Alleen dit onderdeel wordt gepubliceerd.")) void changeRelease(key, { status: "LIVE", beta: true, stable: true, confirm: true }); }}>Vrijgeven aan alle gebruikers</button>}{row.stable && <button className="rollback" disabled={busy} onClick={() => { if (window.confirm(releaseLabel(key) + " terugtrekken naar alleen BETA?")) void changeRelease(key, { status: "TESTEN", beta: true, stable: false, confirm: true }); }}>Terug naar BETA</button>}</span></article>)}</div>
      </details>}
    </section>

    <footer className="v2-footer"><button className="secondary" type="button" disabled={busy || !dirty} onClick={save}>Instellingen opslaan</button><button className="primary" type="button" disabled={busy || !serverConfirmed} onClick={bottomAction}>{busy ? "Bezig…" : enabled ? "Instellingen opslaan" : "Bot activeren"}</button>{message && <p>{message}</p>}</footer>

    <style>{styles}</style>
  </article>;
}

function StepHead({ number, title, subtitle }: { number: string; title: string; subtitle: string }) {
  return <header className="v2-stephead"><b>{number}</b><span><small>STAP {number}</small><h3>{title}</h3><p>{subtitle}</p></span></header>;
}
function Summary({ label, value }: { label: string; value: string }) { return <span><small>{label}</small><b>{value}</b></span>; }
function releaseLabel(key: string) {
  return ({ bot_configurator_v2: "Botconfigurator layout", directional_bollinger: "Directional Bollinger", exposure_refill: "Exposure refill", price_zones: "Price zones", margin_summary: "Margin summary" } as Record<string, string>)[key] || key;
}

const styles = `
#bot-configurator-v2{--gold:#d9b84f;--green:#23d89a;--pink:#ff637e;--panel:#07120f;--panel2:#091914;--muted:#83938b;color:#eef8f3;background:radial-gradient(circle at 75% 0%,rgba(32,190,130,.12),transparent 28%),linear-gradient(180deg,#06100d,#020604);border:1px solid rgba(217,184,79,.46);border-radius:20px;padding:12px;box-shadow:0 24px 70px rgba(0,0,0,.42)}
#bot-configurator-v2 *{box-sizing:border-box}.v2-hero{display:grid;grid-template-columns:1fr auto;gap:12px;align-items:end;padding:6px 4px 12px}.v2-hero h2{font-size:24px;margin:3px 0}.v2-hero p{margin:0;color:#91a198;font-size:11px;max-width:650px;line-height:1.5}.v2-beta{display:inline-flex;border:1px solid rgba(217,184,79,.5);background:rgba(217,184,79,.08);color:#f5d36e;border-radius:999px;padding:5px 8px;font-size:8px;font-weight:900;letter-spacing:.12em}.v2-live{display:flex;align-items:center;gap:8px;padding:7px 9px;border:1px solid #31413a;border-radius:12px;background:#09120f}.v2-live>i{width:10px;height:10px;border-radius:50%;background:#64746c}.v2-live.on>i{background:#4beca9;box-shadow:0 0 10px #32ce8f}.v2-live span{display:grid}.v2-live small{color:#7f8d86;font-size:7px}.v2-live b{font-size:10px}.v2-live button{border:1px solid rgba(255,99,126,.45);background:#251015;color:#ff9aac;border-radius:8px;padding:6px 8px;font-size:8px}
.v2-stepnav{position:sticky;top:0;z-index:15;display:grid;grid-template-columns:repeat(8,minmax(0,1fr));gap:4px;padding:7px 0;margin:0 0 8px;background:linear-gradient(180deg,rgba(3,8,6,.98),rgba(3,8,6,.88),transparent);backdrop-filter:blur(10px)}.v2-stepnav button{display:grid;justify-items:center;gap:3px;min-width:0;border:0;background:transparent;color:#6f8178;font-size:7px;padding:3px 1px}.v2-stepnav b{display:grid;place-items:center;width:20px;height:20px;border-radius:50%;border:1px solid #405048;background:#0a1511}.v2-stepnav button.active{color:#f0d279}.v2-stepnav button.active b{border-color:#d9b84f;color:#101713;background:#d9b84f;box-shadow:0 0 12px rgba(217,184,79,.24)}
.v2-step{scroll-margin-top:58px;display:grid;gap:10px;margin:0 0 10px;padding:12px;border:1px solid rgba(217,184,79,.27);border-radius:16px;background:linear-gradient(180deg,rgba(8,24,18,.97),rgba(3,12,9,.98));box-shadow:inset 0 1px rgba(255,255,255,.025)}.v2-stephead{display:flex;gap:10px;align-items:center;border-bottom:1px solid rgba(255,255,255,.05);padding-bottom:9px}.v2-stephead>b{display:grid;place-items:center;width:32px;height:32px;flex:0 0 32px;border:1px solid var(--gold);border-radius:50%;color:#f5d36e;font-size:13px;background:rgba(217,184,79,.06)}.v2-stephead span{display:grid}.v2-stephead small{color:#b59a4b;font-size:7px;letter-spacing:.12em}.v2-stephead h3{margin:0;font-size:15px}.v2-stephead p{margin:1px 0 0;color:#83938b;font-size:9px}
.v2-grid{display:grid;gap:8px}.v2-grid.cols2{grid-template-columns:repeat(2,minmax(0,1fr))}.v2-field{display:grid;gap:4px;color:#b8c5bf;font-size:8px}.v2-input{display:flex;align-items:center;border:1px solid rgba(217,184,79,.25);border-radius:10px;background:#050d0a;overflow:hidden}.v2-input input{width:100%;height:38px;border:0;outline:0;background:transparent;color:#eef8f3;padding:0 10px;font-size:12px}.v2-input em{padding:0 9px;color:#77877e;font-style:normal;font-size:8px}.v2-field select{height:38px;border:1px solid rgba(217,184,79,.25);border-radius:10px;background:#050d0a;color:#eef8f3;padding:0 9px}.v2-field input:disabled,.v2-field select:disabled{opacity:.45}
.v2-toggle{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center;padding:9px 10px;border:1px solid rgba(89,113,102,.28);border-radius:12px;background:rgba(255,255,255,.015)}.v2-toggle>span{display:grid}.v2-toggle b{font-size:10px}.v2-toggle small{font-size:7.5px;color:#819088;line-height:1.35}.v2-toggle input{position:absolute;opacity:0}.v2-toggle>i{width:38px;height:22px;border-radius:999px;background:#23302a;position:relative;transition:.2s}.v2-toggle>i:after{content:"";position:absolute;width:16px;height:16px;border-radius:50%;left:3px;top:3px;background:#74847b;transition:.2s}.v2-toggle.on>i{background:#107b56;box-shadow:inset 0 0 0 1px #25d99b}.v2-toggle.on>i:after{left:19px;background:#eafff5}.v2-toggle.disabled{opacity:.48}
.v2-sidegrid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.v2-side{display:grid;gap:7px;padding:10px;border-radius:13px;background:rgba(255,255,255,.015)}.v2-side.long{border:1px solid rgba(35,216,154,.32)}.v2-side.short{border:1px solid rgba(255,99,126,.34)}.v2-side.long>b{color:#57ebb2}.v2-side.short>b{color:#ff8da1}.v2-slot-visual{display:grid;grid-template-columns:1fr 1fr auto;gap:7px;align-items:center}.v2-slot-visual>div{display:grid;grid-template-columns:48px 1fr 52px;gap:7px;align-items:center;font-size:9px}.v2-slot-visual i{height:9px;border:1px solid currentColor;border-radius:999px;padding:1px;overflow:hidden}.v2-slot-visual u{display:block;height:100%;background:currentColor;border-radius:999px;box-shadow:0 0 7px currentColor;transition:width .2s ease}.v2-slot-visual b,.v2-slot-visual strong{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}.v2-slot-visual .long{color:#49e6a8}.v2-slot-visual .short{color:#ff6b84}.v2-slot-visual .total{grid-template-columns:auto auto;color:#e7c766}.v2-note{color:#73847b;font-size:7.5px}
.v2-runtime-strip,.v2-account-strip{display:grid;grid-template-columns:repeat(3,1fr);border:1px solid rgba(35,216,154,.19);border-radius:11px;overflow:hidden}.v2-runtime-strip span,.v2-account-strip span{display:grid;padding:8px;border-right:1px solid rgba(35,216,154,.14)}.v2-runtime-strip span:last-child,.v2-account-strip span:last-child{border-right:0}.v2-runtime-strip small,.v2-account-strip small{font-size:7px;color:#7f8f87}.v2-runtime-strip b,.v2-account-strip b{font-size:10px}.v2-runtime-strip b.long{color:#4ce8aa}.v2-runtime-strip b.short{color:#ff7e94}
.v2-tabs{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}.v2-tabs button{height:36px;border:1px solid rgba(217,184,79,.26);border-radius:10px;background:#07130f;color:#87988f;font-size:9px;font-weight:850}.v2-tabs button.active{border-color:#d9b84f;background:linear-gradient(180deg,#987019,#5d430d);color:#fff1c5}
.v2-advanced{border:1px solid rgba(217,184,79,.18);border-radius:12px;padding:8px}.v2-advanced summary{cursor:pointer;font-size:9px;font-weight:800;color:#d6c07b}.v2-advanced>p{font-size:8px;color:#819088;line-height:1.5}.v2-feature-note{display:flex;justify-content:space-between;gap:10px;padding:8px;border-radius:9px;background:#07110e}.v2-feature-note b{font-size:9px}.v2-feature-note span{font-size:8px;color:#e2bd5d}
.v2-summary{display:grid;grid-template-columns:repeat(2,1fr);gap:7px}.v2-summary>span{display:grid;gap:2px;padding:9px;border:1px solid rgba(217,184,79,.18);border-radius:10px;background:rgba(255,255,255,.015)}.v2-summary small{font-size:7px;color:#7f8e87}.v2-summary b{font-size:9px}.v2-capacity{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}.v2-capacity span{display:grid;padding:8px;border:1px solid rgba(35,216,154,.21);border-radius:10px}.v2-capacity small{font-size:6.5px;color:#819188}.v2-capacity b{font-size:10px}.v2-warning{margin:0;padding:8px;border:1px solid rgba(255,173,91,.35);border-radius:10px;background:rgba(144,79,16,.12);color:#ffc78c;font-size:8px;line-height:1.4}
.v2-release-center{border:1px solid rgba(217,184,79,.28);border-radius:12px;padding:9px}.v2-release-center summary{cursor:pointer;color:#efd373;font-size:10px;font-weight:900}.v2-release-center>p{color:#7f8e87;font-size:8px}.v2-release-list{display:grid;gap:6px}.v2-release-list article{display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center;padding:8px;border:1px solid rgba(255,255,255,.06);border-radius:10px}.v2-release-list article>div{display:grid}.v2-release-list b{font-size:9px}.v2-release-list small{font-size:7px;color:#7d8d85}.v2-release-list button{border:1px solid rgba(35,216,154,.4);border-radius:8px;background:#0a3a29;color:#b9f8dd;padding:6px 8px;font-size:7.5px;font-weight:850}.v2-release-list button.rollback{border-color:rgba(255,99,126,.38);background:#2d1016;color:#ff9bae}
.v2-footer{display:grid;grid-template-columns:auto 1fr;gap:8px;position:sticky;bottom:0;z-index:14;padding:10px 0 2px;background:linear-gradient(0deg,rgba(2,6,4,.99) 70%,transparent)}.v2-footer button{height:46px;border-radius:13px;font-weight:900}.v2-footer .secondary{border:1px solid rgba(217,184,79,.36);background:#111914;color:#d5c891;padding:0 14px}.v2-footer .primary{border:1px solid #20df9c;background:linear-gradient(180deg,#0e9667,#086544);color:white}.v2-footer p{grid-column:1/-1;margin:0;padding:6px 8px;border-radius:9px;background:#09120f;color:#b7c7bf;font-size:8px}
@media(max-width:700px){#bot-configurator-v2{padding:8px;border-radius:15px}.v2-hero{grid-template-columns:1fr}.v2-stepnav{overflow-x:auto;grid-template-columns:repeat(8,60px);justify-content:start}.v2-grid.cols2,.v2-sidegrid,.v2-summary{grid-template-columns:1fr 1fr}.v2-capacity{grid-template-columns:1fr 1fr}.v2-release-list article{grid-template-columns:1fr}.v2-slot-visual{grid-template-columns:1fr}.v2-footer{grid-template-columns:1fr 1.35fr}.v2-hero h2{font-size:20px}}
@media(max-width:430px){.v2-grid.cols2,.v2-sidegrid,.v2-summary{grid-template-columns:1fr 1fr}.v2-step{padding:9px}.v2-stephead h3{font-size:13px}.v2-runtime-strip,.v2-account-strip{grid-template-columns:1fr 1fr 1fr}.v2-capacity{grid-template-columns:1fr 1fr}}
`;
