"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

const VISUAL_REFERENCES = {
  strategy: "file_00000000e820820abd4c0803c0faf72c",
  settings: "file_00000000d4188243af425d77dce05825",
  entry: "file_00000000e3d88246868c97243a4217e0",
  review: "file_000000001aec8210ae97ce7474fad735",
  leverage: "file_00000000e5a88210923fcf9378f4bbb6",
  positionSize: "file_00000000d50c82438453f4be8cb1afc3",
  smartRescue: "file_0000000073288210ad62e9dfbb148202",
  protection: "file_0000000015c482109ffb7e3e4b6e4efe",
  refill: "file_00000000d18082108f0116c9afb082e9",
  currentSettings: "file_0000000064fc8210b631ce0a8caebb42",
  quickEdit: "file_000000003b5081f4bee8a56187006a03",
  livePlacement: "file_00000000113c82108f6f3daf44f3627e",
  portfolioSeatReset: "file_00000000369082108949b160b28e0965",
} as const;
const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;
type Timeframe = typeof TIMEFRAMES[number];
type TpMode = "PER_TRADE" | "PORTFOLIO" | "OFF";
type ReleaseFeature = { key?: string; status?: string; beta?: boolean; stable?: boolean; enabled?: boolean; ownerOnly?: boolean; updatedAt?: unknown };
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
  maximumPositions: string;
  zoneLongSeats: string;
  zoneShortSeats: string;
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
  zoneSoldiersEnabled: boolean;
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
  portfolioTpBaseMode: "CYCLE_START" | "CURRENT_VALUE" | "CUSTOM";
  portfolioTpCustomBase: string;
  resetSeatsAfterPortfolioTp: boolean;
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
const nDefault = (value: unknown, fallback: number) => {
  const raw = String(value ?? "").trim();
  if (!raw) return fallback;
  const number = Number(raw.replace(",", "."));
  return Number.isFinite(number) ? number : fallback;
};
const pctText = (value: unknown, fallback: number) => String(n(value, fallback) * 100);
const textValue = (value: unknown, fallback: number) => String(Number.isFinite(Number(value)) ? Number(value) : fallback);
const tf = (value: unknown, fallback: Timeframe): Timeframe => TIMEFRAMES.includes(String(value) as Timeframe) ? String(value) as Timeframe : fallback;
const money = (value: number) => value.toLocaleString("nl-NL", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const compactNumber = (value: unknown, digits = 2) => n(value, 0).toLocaleString("nl-NL", { minimumFractionDigits: 0, maximumFractionDigits: digits });
const compactUsd = (value: unknown, digits = 2) => "$" + n(value, 0).toLocaleString("nl-NL", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const compactPct = (value: unknown, digits = 2) => compactNumber(value, digits) + "%";
const editableDecimal = (value: unknown, digits = 2) => n(value, 0).toFixed(digits).replace(".", ",");

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
    maximumPositions: textValue(settings.maximumPositions, n(settings.longSlots, 20) + n(settings.shortSlots, 10)),
    zoneLongSeats: textValue(settings.zoneBaseLongSoldiers, 3),
    zoneShortSeats: textValue(settings.zoneBaseShortSoldiers, 3),
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
    zoneSoldiersEnabled: settings.zoneSoldiersEnabled === true && n(settings.zoneSoldiersOptInVersion, 0) >= 1,
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
    portfolioTpBaseMode: ["CURRENT_VALUE", "CUSTOM"].includes(String(settings.portfolioTpBaseMode || "").toUpperCase()) ? String(settings.portfolioTpBaseMode).toUpperCase() as "CURRENT_VALUE" | "CUSTOM" : "CYCLE_START",
    portfolioTpCustomBase: n(settings.portfolioTpCustomBaseEquity, 0) > 0 ? textValue(settings.portfolioTpCustomBaseEquity, 0) : "",
    resetSeatsAfterPortfolioTp: settings.resetSeatsAfterPortfolioTp === true,
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

function normalizeQuickDraft(settings: Record<string, unknown>): Draft {
  const base = normalizeDraft(settings);
  return {
    ...base,
    entryMarginLong: editableDecimal(base.entryMarginLong),
    entryMarginShort: editableDecimal(base.entryMarginShort),
    entryNotionalLong: editableDecimal(base.entryNotionalLong),
    entryNotionalShort: editableDecimal(base.entryNotionalShort),
    longDcaAmount: editableDecimal(base.longDcaAmount),
    shortDcaAmount: editableDecimal(base.shortDcaAmount),
    longDcaDistance: editableDecimal(base.longDcaDistance),
    shortDcaDistance: editableDecimal(base.shortDcaDistance),
    longTp: editableDecimal(base.longTp),
    shortTp: editableDecimal(base.shortTp),
    stopLossLong: editableDecimal(base.stopLossLong),
    stopLossShort: editableDecimal(base.stopLossShort),
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

type QuickIconName = "settings" | "edit" | "layers" | "seats" | "entry" | "dca" | "target" | "leverage" | "info" | "reset";

function QuickIcon({ name }: { name: QuickIconName }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  const paths: Record<QuickIconName, ReactNode> = {
    settings: <><circle cx="12" cy="12" r="3" {...common}/><path d="M19 13.5v-3l-2.1-.5a7.4 7.4 0 0 0-.8-1.8l1.1-1.9-2.1-2.1-1.9 1.1a7.4 7.4 0 0 0-1.8-.8L10.9 1h-3l-.5 2.1a7.4 7.4 0 0 0-1.8.8L3.7 2.8 1.6 4.9l1.1 1.9a7.4 7.4 0 0 0-.8 1.8L0 9.1v3l1.9.5c.2.7.5 1.3.8 1.9l-1.1 1.9 2.1 2.1 1.9-1.1c.6.4 1.2.6 1.8.8l.5 2.1h3l.5-2.1c.7-.2 1.3-.5 1.9-.8l1.9 1.1 2.1-2.1-1.1-1.9c.4-.6.6-1.2.8-1.9L19 13.5Z" transform="translate(2 1)" {...common}/></>,
    edit: <><path d="m4 16-1 5 5-1L19 9l-4-4L4 16Z" {...common}/><path d="m13.8 6.2 4 4M15 4l2-2 4 4-2 2" {...common}/></>,
    layers: <><path d="m12 3 9 5-9 5-9-5 9-5Z" {...common}/><path d="m3 12 9 5 9-5M3 16l9 5 9-5" {...common}/></>,
    seats: <><ellipse cx="12" cy="6" rx="7" ry="3" {...common}/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" {...common}/></>,
    entry: <><path d="M4 12h12M12 7l5 5-5 5" {...common}/><path d="M4 5a9 9 0 1 0 0 14" {...common}/></>,
    dca: <><ellipse cx="12" cy="5" rx="7" ry="3" {...common}/><path d="M5 5v5c0 1.7 3.1 3 7 3s7-1.3 7-3V5M5 10v5c0 1.7 3.1 3 7 3s7-1.3 7-3v-5M5 15v4c0 1.7 3.1 3 7 3s7-1.3 7-3v-4" {...common}/></>,
    target: <><circle cx="12" cy="12" r="8" {...common}/><circle cx="12" cy="12" r="4" {...common}/><path d="M12 1v4M23 12h-4M12 23v-4M1 12h4" {...common}/></>,
    leverage: <><path d="M4 18h3V8H4v10Zm6 0h3V4h-3v14Zm6 0h3v-7h-3v7Z" {...common}/></>,
    info: <><circle cx="12" cy="12" r="9" {...common}/><path d="M12 11v6M12 7h.01" {...common}/></>,
    reset: <><path d="M4 8V3m0 0h5M4 3l3 3a8 8 0 1 1-2 8" {...common}/></>,
  };
  return <svg className="v31-icon" viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

function QuickStepper({ value, onChange, step = 1, min = 0, max, prefix, suffix, tone }: {
  value: string; onChange: (value: string) => void; step?: number; min?: number; max?: number; prefix?: string; suffix?: string; tone?: "long" | "short";
}) {
  const decimals = Math.max(0, String(step).split(".")[1]?.length ?? 0, String(value).replace(",", ".").split(".")[1]?.length ?? 0);
  const change = (delta: number) => {
    const raw = n(value, 0) + delta * step;
    const bounded = Math.min(max ?? Number.POSITIVE_INFINITY, Math.max(min, raw));
    const next = bounded.toFixed(Math.min(4, decimals || (step < 1 ? 2 : 0)));
    onChange(next.replace(".", ","));
  };
  return <div className={"v31-stepper " + (tone || "")}>
    <button type="button" aria-label="Verlagen" onClick={() => change(-1)}>−</button>
    <label><span>{prefix}</span><input inputMode="decimal" value={value} onChange={(e) => onChange(e.target.value)} /><em>{suffix}</em></label>
    <button type="button" aria-label="Verhogen" onClick={() => change(1)}>+</button>
  </div>;
}

function QuickSettingSection({ id, icon, title, subtitle, children, layout = "default" }: { id?: string; icon: QuickIconName; title: string; subtitle: string; children: ReactNode; layout?: "default" | "rows" }) {
  return <section id={id} className={"v31-setting-card " + (layout === "rows" ? "rows" : "")}>
    <span className="v31-setting-icon"><QuickIcon name={icon}/></span>
    <div className="v31-setting-copy"><h4>{title}</h4><p>{subtitle}</p></div>
    <div className="v31-setting-control">{children}</div>
  </section>;
}

const STEP_LABELS = [
  ["strategy", "Strategie"], ["settings", "Instellingen"], ["entry", "Instap & DCA"], ["review", "Controleren"],
] as const;

export function AsterBotConfiguratorV3({ snapshot, serverConfirmed, onConfirmed, onChanged, release }: Props) {
  const strategy2 = snapshot?.strategy2 && typeof snapshot.strategy2 === "object" ? snapshot.strategy2 as Record<string, unknown> : {};
  const persisted = strategy2.settings && typeof strategy2.settings === "object" ? strategy2.settings as Record<string, unknown> : {};
  const enabled = strategy2.enabled === true;
  const report = strategy2.multiBb && typeof strategy2.multiBb === "object" ? strategy2.multiBb as Record<string, unknown> :
    strategy2.multiBbReport && typeof strategy2.multiBbReport === "object" ? strategy2.multiBbReport as Record<string, unknown> : {};
  const priceZoneSeats = strategy2.priceZoneSeats && typeof strategy2.priceZoneSeats === "object"
    ? strategy2.priceZoneSeats as Record<string, unknown>
    : strategy2.zoneSoldiers && typeof strategy2.zoneSoldiers === "object"
      ? strategy2.zoneSoldiers as Record<string, unknown>
      : {};
  const seatModel = priceZoneSeats.seatModel && typeof priceZoneSeats.seatModel === "object"
    ? priceZoneSeats.seatModel as Record<string, unknown>
    : {};
  const [draft, setDraft] = useState<Draft>(() => normalizeDraft(persisted));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [currentStep, setCurrentStep] = useState(1);
  const [settingsAccordion, setSettingsAccordion] = useState<"market" | "leverage" | "size" | null>("market");
  const [entryAccordion, setEntryAccordion] = useState<"filters" | "rescue" | "protection" | "refill" | null>("filters");
  const [releases, setReleases] = useState<ReleaseState>(release);
  const [confirmedSettings, setConfirmedSettings] = useState<Record<string, unknown>>(persisted);
  const [quickEditOpen, setQuickEditOpen] = useState(false);
  const [quickDraft, setQuickDraft] = useState<Draft>(() => normalizeQuickDraft(persisted));
  const [quickDirty, setQuickDirty] = useState(false);
  const [quickAdvanced, setQuickAdvanced] = useState(false);
  const [quickFocus, setQuickFocus] = useState<"entry" | "seats" | null>(null);

  useEffect(() => {
    if (!dirty) setDraft(normalizeDraft(persisted));
  }, [JSON.stringify(persisted), dirty]);

  useEffect(() => {
    setConfirmedSettings(persisted);
    if (!quickDirty) setQuickDraft(normalizeQuickDraft(persisted));
  }, [JSON.stringify(persisted), quickDirty]);

  useEffect(() => {
    if (!quickEditOpen || !quickFocus) return;
    requestAnimationFrame(() => {
      document.getElementById(quickFocus === "entry" ? "v31-entry-amount" : "v31-max-seats")?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }, [quickEditOpen, quickFocus]);


  const ownerBeta = releases.channel === "BETA";
  const feature = (key: string) => releases.features?.[key] ?? release.features?.[key] ?? {};
  const directionalAvailable = feature("directional_bollinger").enabled === true;
  const exposureAvailable = feature("exposure_refill").enabled === true;
  const marginSummaryAvailable = feature("margin_summary").enabled === true;
  const priceZonesAvailable = feature("price_zones").enabled === true;
  const zoneSoldiersAvailable = feature("zone_soldiers").enabled === true;
  const savedZoneStrategyEnabled = zoneSoldiersAvailable && persisted.zoneSoldiersEnabled === true && n(persisted.zoneSoldiersOptInVersion, 0) >= 1;
  const zoneLifecycle = String(strategy2.zoneSoldierLifecycle || (savedZoneStrategyEnabled ? "ACTIVE" : "OFF")).toUpperCase();
  const strategyBadge = savedZoneStrategyEnabled ? "STRATEGIE · ZONE WARRIORS" : zoneLifecycle === "DRAINING" ? "STRATEGIE · ZONE WARRIORS AFBOUWEN" : "STRATEGIE · CLASSIC DCA";

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
  const exposureSide = String(report.exposureRefillSide || "").toUpperCase();
  const imbalance = n(report.exposureImbalancePercent, 0);
  const savedExposureRefillEnabled = exposureAvailable && persisted.exposureRefillEnabled === true;
  const exposureRefillPendingSave = exposureAvailable && draft.exposureRefillEnabled !== savedExposureRefillEnabled;
  const exposureRuntimeLabel = !savedExposureRefillEnabled
    ? "UIT"
    : exposureSide === "LONG" || exposureSide === "SHORT"
      ? `${exposureSide} versneld`
      : "stand-by";
  const liveLongRaw = Number(report.activeLong);
  const liveShortRaw = Number(report.activeShort);
  const activeLong = Number.isFinite(liveLongRaw) ? Math.max(0, Math.round(liveLongRaw)) : null;
  const activeShort = Number.isFinite(liveShortRaw) ? Math.max(0, Math.round(liveShortRaw)) : null;
  const activeTotal = activeLong !== null && activeShort !== null ? activeLong + activeShort : null;
  const zoneLongSeats = Math.max(1, Math.round(n(draft.zoneLongSeats, 3)));
  const zoneShortSeats = Math.max(1, Math.round(n(draft.zoneShortSeats, 3)));
  const maxActiveSeats = Math.max(1, Math.round(n(draft.maximumPositions, totals.totalSlots || 30)));
  const zoneActiveRaw = Number(seatModel.activeZone ?? priceZoneSeats.activeZone);
  const zoneActive = Number.isFinite(zoneActiveRaw) ? Math.round(zoneActiveRaw) : null;
  const activeZoneOpenLong = Math.max(0, Math.round(n(seatModel.occupiedLongActiveZone, 0)));
  const activeZoneOpenShort = Math.max(0, Math.round(n(seatModel.occupiedShortActiveZone, 0)));
  const freeZoneLong = Math.max(0, zoneLongSeats - activeZoneOpenLong);
  const freeZoneShort = Math.max(0, zoneShortSeats - activeZoneOpenShort);
  const oldZonesOpen = Math.max(0, Math.round(n(seatModel.openFromOldZones, 0)));
  const strategyOpenLong = Math.max(0, Math.round(n(seatModel.strategyOpenLong, activeLong ?? 0)));
  const strategyOpenShort = Math.max(0, Math.round(n(seatModel.strategyOpenShort, activeShort ?? 0)));
  const strategyOpenTotal = Math.max(0, Math.round(n(seatModel.strategyOpenTotal, strategyOpenLong + strategyOpenShort)));
  const sideWeightTotal = Math.max(1, zoneLongSeats + zoneShortSeats);
  const globalLongCapacity = Math.max(1, Math.round(maxActiveSeats * zoneLongSeats / sideWeightTotal));
  const globalShortCapacity = Math.max(0, maxActiveSeats - globalLongCapacity);
  const zoneLabel = zoneActive === null ? "Zone —" : `Zone ${zoneActive}`;
  const slotFill = (active: number | null, capacity: number) => active === null
    ? 0
    : capacity <= 0
      ? (active > 0 ? 100 : 0)
      : Math.min(100, Math.max(0, active / capacity * 100));

  function draftTotals(source: Draft) {
    const longSlots = Math.max(0, Math.round(n(source.longSlots)));
    const shortSlots = Math.max(0, Math.round(n(source.shortSlots)));
    const totalSlots = longSlots + shortSlots;
    return { longSlots, shortSlots, totalSlots };
  }

  function assertConfirmedSeatLimitFor(source: Draft, confirmed: Record<string, unknown> | null) {
    if (!source.zoneSoldiersEnabled || !confirmed) return;
    const confirmedSettingsValue = confirmed.settings && typeof confirmed.settings === "object"
      ? confirmed.settings as Record<string, unknown>
      : {};
    const requestedMaximum = Math.max(1, Math.round(n(source.maximumPositions, 1)));
    const confirmedMaximum = Number(confirmedSettingsValue.maximumPositions);
    if (!Number.isFinite(confirmedMaximum) || Math.round(confirmedMaximum) !== requestedMaximum) {
      throw new Error(`Opslaan niet bevestigd: gevraagd max ${requestedMaximum}, server bevestigde ${Number.isFinite(confirmedMaximum) ? Math.round(confirmedMaximum) : "geen waarde"}.`);
    }
  }

  function assertConfirmedSeatLimit(confirmed: Record<string, unknown> | null) {
    assertConfirmedSeatLimitFor(draft, confirmed);
  }

  function buildSettingsFrom(source: Draft) {
    const sourceTotals = draftTotals(source);
    const sourceZoneLongSeats = Math.max(1, Math.round(n(source.zoneLongSeats, 3)));
    const sourceZoneShortSeats = Math.max(1, Math.round(n(source.zoneShortSeats, 3)));
    const sourceMaxActiveSeats = Math.max(1, Math.round(n(source.maximumPositions, sourceTotals.totalSlots || 30)));
    if (!source.zoneSoldiersEnabled && (sourceTotals.totalSlots < 1 || sourceTotals.totalSlots > 400)) throw new Error("LONG + SHORT moet tussen 1 en 400 posities liggen.");
    if (source.zoneSoldiersEnabled && (sourceMaxActiveSeats < 1 || sourceMaxActiveSeats > 400)) throw new Error("Max actieve stoelen moet tussen 1 en 400 liggen.");
    if (source.zoneSoldiersEnabled && (sourceZoneLongSeats < 1 || sourceZoneLongSeats > 100 || sourceZoneShortSeats < 1 || sourceZoneShortSeats > 100)) throw new Error("LONG/SHORT-stoelen per prijszone moeten tussen 1 en 100 liggen.");
    const minLev = Math.max(1, Math.round(n(source.minimumLeverage)));
    const maxLev = source.maximumLeverage.trim() ? Math.max(1, Math.round(n(source.maximumLeverage))) : null;
    if (maxLev !== null && maxLev < minLev) throw new Error("Maximum leverage kan niet lager zijn dan minimum leverage.");
    if (n(source.longDcaDistance) <= 0 || n(source.shortDcaDistance) <= 0 || n(source.longDcaDistance) > 50 || n(source.shortDcaDistance) > 50) throw new Error("DCA-afstand moet tussen 0 en 50% liggen.");
    if ([source.entryMarginLong, source.entryMarginShort, source.longDcaAmount, source.shortDcaAmount].some((value) => n(value) < 0)) throw new Error("Instap- en DCA-bedragen mogen niet negatief zijn.");
    if (source.fixedPositionSize && [source.entryNotionalLong, source.entryNotionalShort].some((value) => n(value) < 0)) throw new Error("Vaste positiebedragen mogen niet negatief zijn.");
    if (n(source.maxDcaLong) < 0 || n(source.maxDcaShort) < 0) throw new Error("Max DCA mag niet negatief zijn.");
    if (n(source.exposureRefillReleasePercent) < 0 || n(source.exposureRefillReleasePercent) >= n(source.exposureRefillTriggerPercent)) throw new Error("Exposure stopdrempel moet lager zijn dan de startdrempel.");
    if (source.tpMode === "PORTFOLIO" && source.portfolioTpBaseMode === "CUSTOM" && n(source.portfolioTpCustomBase) <= 0) throw new Error("Vul een geldige aangepaste Portfolio TP-basis in.");
    const sizing = source.fixedPositionSize ? {
      entrySizingMode: "notional",
      entryNotionalUsd: n(source.entryNotionalLong),
      entryNotionalLongUsd: n(source.entryNotionalLong),
      entryNotionalShortUsd: n(source.entryNotionalShort),
      entryNotionalLong: n(source.entryNotionalLong),
      entryNotionalShort: n(source.entryNotionalShort),
    } : { entrySizingMode: "margin" };
    return {
      ...confirmedSettings,
      engine: "multi_bb_v1",
      strategyKind: "multi_bb_v1",
      name: source.name,
      universeTopN: Math.max(1, Math.round(n(source.universeTopN))),
      maximumPositions: source.zoneSoldiersEnabled ? sourceMaxActiveSeats : sourceTotals.totalSlots,
      longSlots: sourceTotals.longSlots,
      shortSlots: sourceTotals.shortSlots,
      minimumLeverage: minLev,
      maximumLeverage: maxLev,
      manualSymbolSelectionEnabled: source.manualEnabled,
      manualSymbols: source.manualEnabled ? parseManual(source.manualSymbols) : [],
      bollingerEntryFilter15mEnabled: source.bollingerEnabled,
      bollingerEntryFilterTimeframe: source.bollingerLongTimeframe,
      ...(directionalAvailable ? {
        directionalBollingerEnabled: source.directionalBollingerEnabled,
        bollingerLongTimeframe: source.bollingerLongTimeframe,
        bollingerShortTimeframe: source.bollingerShortTimeframe,
      } : {}),
      ...(exposureAvailable ? {
        exposureRefillEnabled: source.exposureRefillEnabled,
        exposureRefillLongTimeframe: source.exposureRefillLongTimeframe,
        exposureRefillShortTimeframe: source.exposureRefillShortTimeframe,
        exposureRefillTriggerPercent: n(source.exposureRefillTriggerPercent),
        exposureRefillReleasePercent: n(source.exposureRefillReleasePercent),
      } : {}),
      ...(zoneSoldiersAvailable ? {
        zoneSoldiersEnabled: source.zoneSoldiersEnabled,
        zoneSoldiersOptInVersion: source.zoneSoldiersEnabled ? 1 : 0,
        zoneBaseLongSoldiers: sourceZoneLongSeats,
        zoneBaseShortSoldiers: sourceZoneShortSeats,
        zoneExposureBalancerEnabled: confirmedSettings.zoneExposureBalancerEnabled !== false,
        zoneEntryGrowthPercent: nDefault(confirmedSettings.zoneEntryGrowthPercent, 2),
        zoneEntryMaxMultiplier: nDefault(confirmedSettings.zoneEntryMaxMultiplier, 1.2),
      } : { zoneSoldiersEnabled: false, zoneSoldiersOptInVersion: 0 }),
      ...sizing,
      entryMarginUsd: n(source.entryMarginLong),
      entryMarginLongUsd: n(source.entryMarginLong),
      entryMarginShortUsd: n(source.entryMarginShort),
      entryMarginLong: n(source.entryMarginLong),
      entryMarginShort: n(source.entryMarginShort),
      dcaDistance: n(source.longDcaDistance) / 100,
      longDcaDistance: n(source.longDcaDistance) / 100,
      shortDcaDistance: n(source.shortDcaDistance) / 100,
      dcaMarginUsd: n(source.longDcaAmount),
      longDcaMarginUsd: n(source.longDcaAmount),
      shortDcaMarginUsd: n(source.shortDcaAmount),
      longDcaAmount: n(source.longDcaAmount),
      shortDcaAmount: n(source.shortDcaAmount),
      maxDca: Math.max(0, Math.round(n(source.maxDcaLong))),
      maxDcaLong: Math.max(0, Math.round(n(source.maxDcaLong))),
      maxDcaShort: Math.max(0, Math.round(n(source.maxDcaShort))),
      longMaxDca: Math.max(0, Math.round(n(source.maxDcaLong))),
      shortMaxDca: Math.max(0, Math.round(n(source.maxDcaShort))),
      takeProfitMode: source.tpMode,
      takeProfitEnabled: source.tpMode !== "OFF",
      takeProfit: n(source.longTp) / 100,
      longTakeProfitValue: n(source.longTp) / 100,
      shortTakeProfitValue: n(source.shortTp) / 100,
      takeProfitLong: n(source.longTp) / 100,
      takeProfitShort: n(source.shortTp) / 100,
      portfolioTpValue: n(source.portfolioTpValue),
      portfolioTpInputMode: source.portfolioTpInputMode,
      portfolioTpBaseMode: source.portfolioTpBaseMode,
      portfolioTpCustomBaseEquity: n(source.portfolioTpCustomBase),
      resetSeatsAfterPortfolioTp: source.resetSeatsAfterPortfolioTp,
      shortRequiresLongEnabled: source.shortRequiresLongEnabled,
      stopLossEnabled: source.stopLossEnabled,
      stopLossMode: source.stopLossMode,
      stopLossLong: n(source.stopLossLong),
      stopLossShort: n(source.stopLossShort),
      smartRescueEnabled: source.smartRescueEnabled,
      smartRescueRangePercent: n(source.smartRescueRange),
      smartRescueDcaCount: Math.max(1, Math.round(n(source.smartRescueCount))),
      smartRescueOrderGrowthMultiplier: Math.max(1, n(source.smartRescueGrowth)),
      smartRescueTrailingRecoveryPercent: Math.max(0, n(source.smartRescueRecovery)),
      entryMode: "immediate_fill",
      marginMode: "cross",
      autoRestart: true,
    };
  }

  function buildSettings() {
    return buildSettingsFrom(draft);
  }

  async function save() {
    setBusy(true); setMessage("");
    try {
      const settings = buildSettings();
      const result = await authenticatedRequest("/api/exchanges/aster/strategy2/settings", { method: "PUT", body: JSON.stringify({ settings }) }) as Record<string, unknown>;
      const confirmed = result.strategy2 && typeof result.strategy2 === "object" ? result.strategy2 as Record<string, unknown> : null;
      if (!confirmed) throw new Error("Server heeft de instellingen niet bevestigd.");
      assertConfirmedSeatLimit(confirmed);
      onConfirmed(confirmed);
      if (confirmed.settings && typeof confirmed.settings === "object") setConfirmedSettings(confirmed.settings as Record<string, unknown>);
      setDirty(false);
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
        if (!confirmed) throw new Error("Server heeft de instellingen niet bevestigd.");
        assertConfirmedSeatLimit(confirmed);
        onConfirmed(confirmed);
        if (confirmed.settings && typeof confirmed.settings === "object") setConfirmedSettings(confirmed.settings as Record<string, unknown>);
        setDirty(false); setMessage("Instellingen opgeslagen; actieve bot-state is behouden.");
      } else {
        const result = await authenticatedRequest("/api/exchanges/aster/strategy2/start", { method: "POST", body: JSON.stringify({ confirm: true, settings }) }) as Record<string, unknown>;
        const confirmed = result.strategy2 && typeof result.strategy2 === "object" ? result.strategy2 as Record<string, unknown> : null;
        if (!confirmed) throw new Error("Server heeft de instellingen niet bevestigd.");
        assertConfirmedSeatLimit(confirmed);
        onConfirmed(confirmed);
        if (confirmed.settings && typeof confirmed.settings === "object") setConfirmedSettings(confirmed.settings as Record<string, unknown>);
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

  const confirmedDraft = useMemo(() => normalizeDraft(confirmedSettings), [JSON.stringify(confirmedSettings)]);
  const confirmedZoneEnabled = confirmedDraft.zoneSoldiersEnabled;
  const confirmedStrategyName = confirmedZoneEnabled ? "Zone Warriors" : "Classic DCA";
  const confirmedLongSeats = Math.max(1, Math.round(n(confirmedDraft.zoneLongSeats, 3)));
  const confirmedShortSeats = Math.max(1, Math.round(n(confirmedDraft.zoneShortSeats, 3)));
  const confirmedClassicLong = Math.max(0, Math.round(n(confirmedDraft.longSlots)));
  const confirmedClassicShort = Math.max(0, Math.round(n(confirmedDraft.shortSlots)));
  const confirmedMaximum = confirmedZoneEnabled
    ? Math.max(1, Math.round(n(confirmedDraft.maximumPositions, 1)))
    : confirmedClassicLong + confirmedClassicShort;
  const confirmedSeatLabel = confirmedZoneEnabled
    ? `${confirmedLongSeats}L + ${confirmedShortSeats}S per zone · max ${confirmedMaximum}`
    : `${confirmedClassicLong} LONG · ${confirmedClassicShort} SHORT · max ${confirmedMaximum}`;
  const confirmedTpLabel = confirmedDraft.tpMode === "OFF"
    ? "Uit"
    : confirmedDraft.tpMode === "PORTFOLIO"
      ? `Portfolio · ${confirmedDraft.portfolioTpInputMode === "USD" ? "$" + compactNumber(confirmedDraft.portfolioTpValue) : compactPct(confirmedDraft.portfolioTpValue)}`
      : `Per trade · L ${compactPct(confirmedDraft.longTp)} / S ${compactPct(confirmedDraft.shortTp)}`;
  const confirmedLeverageLabel = confirmedDraft.maximumLeverage
    ? `${Math.max(1, Math.round(n(confirmedDraft.minimumLeverage)))}x – ${Math.max(1, Math.round(n(confirmedDraft.maximumLeverage)))}x`
    : `${Math.max(1, Math.round(n(confirmedDraft.minimumLeverage)))}x – pair max`;

  const updateQuick = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    setQuickDraft((current) => ({ ...current, [key]: value }));
    setQuickDirty(true);
    setMessage("");
  };

  const openQuickEdit = (focus: "entry" | "seats" | null = null) => {
    setQuickDraft(normalizeQuickDraft(confirmedSettings));
    setQuickDirty(false);
    setQuickAdvanced(false);
    setQuickFocus(focus);
    setQuickEditOpen(true);
    setMessage("");
    requestAnimationFrame(() => document.getElementById("bot-configurator-v3")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  const cancelQuickEdit = () => {
    if (quickDirty && !window.confirm("Wijzigingen niet opslaan?")) return;
    setQuickDraft(normalizeQuickDraft(confirmedSettings));
    setQuickDirty(false);
    setQuickAdvanced(false);
    setQuickFocus(null);
    setQuickEditOpen(false);
    setMessage("");
  };

  const resetQuickEdit = () => {
    setQuickDraft(normalizeQuickDraft(confirmedSettings));
    setQuickDirty(false);
    setMessage("");
  };

  async function saveQuickEdit() {
    if (!quickDirty) return;
    setBusy(true);
    setMessage("");
    try {
      const settings = buildSettingsFrom(quickDraft);
      const result = await authenticatedRequest("/api/exchanges/aster/strategy2/settings", {
        method: "PUT",
        body: JSON.stringify({ settings }),
      }) as Record<string, unknown>;
      const confirmed = result.strategy2 && typeof result.strategy2 === "object" ? result.strategy2 as Record<string, unknown> : null;
      if (!confirmed) throw new Error("Server heeft de instellingen niet bevestigd.");
      assertConfirmedSeatLimitFor(quickDraft, confirmed);
      const serverSettings = confirmed.settings && typeof confirmed.settings === "object"
        ? confirmed.settings as Record<string, unknown>
        : null;
      if (!serverSettings) throw new Error("Server heeft geen bevestigde instellingen teruggestuurd.");
      const checks: Array<[string, number]> = [
        ["entryMarginLongUsd", n(settings.entryMarginLongUsd)],
        ["entryMarginShortUsd", n(settings.entryMarginShortUsd)],
        ["longDcaMarginUsd", n(settings.longDcaMarginUsd)],
        ["shortDcaMarginUsd", n(settings.shortDcaMarginUsd)],
      ];
      for (const [key, expected] of checks) {
        if (serverSettings[key] !== undefined && Math.abs(n(serverSettings[key]) - expected) > 0.000001) {
          throw new Error("Opslaan niet bevestigd: de server gaf een andere waarde terug voor " + key + ".");
        }
      }
      onConfirmed(confirmed);
      setConfirmedSettings(serverSettings);
      setQuickDraft(normalizeQuickDraft(serverSettings));
      setQuickDirty(false);
      setQuickAdvanced(false);
      setQuickFocus(null);
      setQuickEditOpen(false);
      setMessage("Instellingen opgeslagen");
      await Promise.resolve(onChanged());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Opslaan mislukt.");
    } finally {
      setBusy(false);
    }
  }

  const strategyName = draft.zoneSoldiersEnabled ? "Zone Warriors" : "Classic DCA";
  const goTo = (step: number) => {
    setCurrentStep(Math.max(1, Math.min(4, step)));
    requestAnimationFrame(() => document.getElementById("bot-configurator-v3")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };
  const chooseStrategy = (zone: boolean) => {
    if (zone && !zoneSoldiersAvailable) return;
    update("zoneSoldiersEnabled", zone);
  };
  const next = () => goTo(currentStep + 1);
  const previous = () => goTo(currentStep - 1);
  const selectedPositionLabel = draft.zoneSoldiersEnabled
    ? `${zoneLongSeats}L / ${zoneShortSeats}S per zone · max ${maxActiveSeats}`
    : `${totals.longSlots} LONG · ${totals.shortSlots} SHORT · max ${totals.totalSlots}`;
  const tpLabel = draft.tpMode === "OFF"
    ? "Uit"
    : draft.tpMode === "PORTFOLIO"
      ? `Portfolio · ${draft.portfolioTpValue}${draft.portfolioTpInputMode === "USD" ? " USDT" : "%"}`
      : `Per trade · L ${draft.longTp}% / S ${draft.shortTp}%`;

  if (quickEditOpen) {
    const quickClassicTotal = Math.max(0, Math.round(n(quickDraft.longSlots))) + Math.max(0, Math.round(n(quickDraft.shortSlots)));
    return <article id="bot-configurator-v3" className="botconfig-v3 v31-mode" data-version="3.1" data-beta-only="true" data-reference={VISUAL_REFERENCES.quickEdit}>
      <header className="v31-top">
        <div><span className="v3-kicker">BOTCONFIGURATOR 3.0</span><h2>Instellingen wijzigen</h2><p>Pas snel je huidige instellingen aan.</p></div>
        <div className="v3-top-status">{ownerBeta&&<span>BETA</span>}<b className={enabled?"on":""}>{enabled?"BOT AAN":"BOT UIT"}</b></div>
      </header>

      <section className="v31-quick">
        <div className="v31-info"><QuickIcon name="info"/><p>Hier kun je alleen de belangrijkste actieve instellingen aanpassen.<br/>Je strategie en andere geavanceerde instellingen blijven hetzelfde.</p></div>

        <QuickSettingSection icon="layers" title="Strategie" subtitle="Kan hier niet worden gewijzigd.">
          <div className="v31-readonly-value">{confirmedStrategyName}</div>
        </QuickSettingSection>

        <QuickSettingSection id="v31-max-seats" icon="seats" title="Max stoelen" subtitle="Totaal aantal gelijktijdige posities.">
          {quickDraft.zoneSoldiersEnabled
            ? <QuickStepper value={quickDraft.maximumPositions} onChange={(v)=>updateQuick("maximumPositions",v)} step={1} min={1} max={400}/>
            : <div className="v31-sides compact">
                <div><b className="long">↑ LONG</b><QuickStepper value={quickDraft.longSlots} onChange={(v)=>updateQuick("longSlots",v)} step={1} min={0} max={400} tone="long"/></div>
                <div><b className="short">↓ SHORT</b><QuickStepper value={quickDraft.shortSlots} onChange={(v)=>updateQuick("shortSlots",v)} step={1} min={0} max={400} tone="short"/></div>
                <small>Max totaal: {quickClassicTotal}</small>
              </div>}
        </QuickSettingSection>

        <QuickSettingSection id="v31-entry-amount" icon="entry" title="Instapbedrag" subtitle="Bedrag per nieuwe positie." layout="rows">
          <div className="v31-sides">
            <div><b className="long">↑ LONG</b><QuickStepper value={quickDraft.entryMarginLong} onChange={(v)=>updateQuick("entryMarginLong",v)} step={.01} min={0} prefix="$" tone="long"/></div>
            <div><b className="short">↓ SHORT</b><QuickStepper value={quickDraft.entryMarginShort} onChange={(v)=>updateQuick("entryMarginShort",v)} step={.01} min={0} prefix="$" tone="short"/></div>
          </div>
        </QuickSettingSection>

        <QuickSettingSection icon="dca" title="DCA-bedrag" subtitle="Bedrag per extra aankoop (DCA)." layout="rows">
          <div className="v31-sides">
            <div><b className="long">↑ LONG</b><QuickStepper value={quickDraft.longDcaAmount} onChange={(v)=>updateQuick("longDcaAmount",v)} step={.01} min={0} prefix="$" tone="long"/></div>
            <div><b className="short">↓ SHORT</b><QuickStepper value={quickDraft.shortDcaAmount} onChange={(v)=>updateQuick("shortDcaAmount",v)} step={.01} min={0} prefix="$" tone="short"/></div>
          </div>
        </QuickSettingSection>

        <QuickSettingSection icon="target" title="Take profit" subtitle="Winst nemen bij doel.">
          <div className="v31-tp-control">
            <div className="v31-segments">
              <button type="button" className={quickDraft.tpMode==="PORTFOLIO"?"active":""} onClick={()=>updateQuick("tpMode","PORTFOLIO")}>Portfolio</button>
              <button type="button" className={quickDraft.tpMode==="PER_TRADE"?"active":""} onClick={()=>updateQuick("tpMode","PER_TRADE")}>Per positie</button>
            </div>
            {quickDraft.tpMode==="OFF"&&<small className="v31-off-label">Take profit staat uit · wijzig dit onder Meer instellingen</small>}
            {quickDraft.tpMode==="PORTFOLIO"&&<QuickStepper value={quickDraft.portfolioTpValue} onChange={(v)=>updateQuick("portfolioTpValue",v)} step={quickDraft.portfolioTpInputMode==="USD"?1:.1} min={0} prefix={quickDraft.portfolioTpInputMode==="USD"?"$":undefined} suffix={quickDraft.portfolioTpInputMode==="PERCENT"?"%":undefined}/>}
            {quickDraft.tpMode==="PER_TRADE"&&<div className="v31-sides compact">
              <div><b className="long">↑ LONG</b><QuickStepper value={quickDraft.longTp} onChange={(v)=>updateQuick("longTp",v)} step={.1} min={0} suffix="%" tone="long"/></div>
              <div><b className="short">↓ SHORT</b><QuickStepper value={quickDraft.shortTp} onChange={(v)=>updateQuick("shortTp",v)} step={.1} min={0} suffix="%" tone="short"/></div>
            </div>}
          </div>
        </QuickSettingSection>

        <button className={"v31-more "+(quickAdvanced?"open":"")} type="button" onClick={()=>setQuickAdvanced((value)=>!value)} aria-expanded={quickAdvanced}>
          <span>{quickAdvanced?"⌃":"⌄"}</span> Meer instellingen tonen
        </button>

        {quickAdvanced&&<div className="v31-advanced" data-expanded="true">
          <section><h4>Markt & selectie</h4><div className="v3-grid two"><Field label="Top-N volume" value={quickDraft.universeTopN} onChange={(v)=>updateQuick("universeTopN",v)} min={1}/><Field label="Botnaam" type="text" value={quickDraft.name} onChange={(v)=>updateQuick("name",v)}/></div><Toggle label="Zelf munten kiezen" description="Uit = automatische Top-N. Aan = alleen jouw selectie." checked={quickDraft.manualEnabled} onChange={(v)=>updateQuick("manualEnabled",v)}/>{quickDraft.manualEnabled&&<Field label="Munten · SYMBOL:LONG / SYMBOL:SHORT" type="text" value={quickDraft.manualSymbols} onChange={(v)=>updateQuick("manualSymbols",v)}/>}</section>

          {quickDraft.zoneSoldiersEnabled&&<section><h4>Zone Warriors</h4><div className="v3-grid two"><Field label="LONG stoelen per zone" value={quickDraft.zoneLongSeats} onChange={(v)=>updateQuick("zoneLongSeats",v)}/><Field label="SHORT stoelen per zone" value={quickDraft.zoneShortSeats} onChange={(v)=>updateQuick("zoneShortSeats",v)}/></div></section>}

          <section><h4>DCA</h4><div className="v3-grid two"><Field label="LONG DCA-afstand" value={quickDraft.longDcaDistance} onChange={(v)=>updateQuick("longDcaDistance",v)} suffix="%"/><Field label="SHORT DCA-afstand" value={quickDraft.shortDcaDistance} onChange={(v)=>updateQuick("shortDcaDistance",v)} suffix="%"/><Field label="LONG Max DCA" value={quickDraft.maxDcaLong} onChange={(v)=>updateQuick("maxDcaLong",v)}/><Field label="SHORT Max DCA" value={quickDraft.maxDcaShort} onChange={(v)=>updateQuick("maxDcaShort",v)}/></div></section>

          <section><h4>Leverage</h4><div className="v3-grid two"><Field label="Minimum leverage" value={quickDraft.minimumLeverage} onChange={(v)=>updateQuick("minimumLeverage",v)} suffix="x"/><Field label="Maximum leverage" value={quickDraft.maximumLeverage} onChange={(v)=>updateQuick("maximumLeverage",v)} suffix="x"/></div></section>

          <section><h4>Positiegrootte</h4><Toggle label="Vaste positieomvang" description="Uit = margin. Aan = vaste notional in USDT." checked={quickDraft.fixedPositionSize} onChange={(v)=>updateQuick("fixedPositionSize",v)}/>{quickDraft.fixedPositionSize&&<div className="v3-grid two"><Field label="LONG vaste positie" value={quickDraft.entryNotionalLong} onChange={(v)=>updateQuick("entryNotionalLong",v)} suffix="USDT"/><Field label="SHORT vaste positie" value={quickDraft.entryNotionalShort} onChange={(v)=>updateQuick("entryNotionalShort",v)} suffix="USDT"/></div>}</section>

          <section><h4>Instapfilters</h4><Toggle label="Bollinger instapfilter" description="Alleen voor nieuwe initial entries." checked={quickDraft.bollingerEnabled} onChange={(v)=>updateQuick("bollingerEnabled",v)}/><div className="v3-grid two"><TimeframeSelect label="LONG timeframe" value={quickDraft.bollingerLongTimeframe} onChange={(v)=>updateQuick("bollingerLongTimeframe",v)} disabled={!quickDraft.bollingerEnabled}/><TimeframeSelect label="SHORT timeframe" value={quickDraft.bollingerShortTimeframe} onChange={(v)=>updateQuick("bollingerShortTimeframe",v)} disabled={!quickDraft.bollingerEnabled||!directionalAvailable}/></div><Toggle label="LONG en SHORT apart" checked={quickDraft.directionalBollingerEnabled} onChange={(v)=>updateQuick("directionalBollingerEnabled",v)} disabled={!directionalAvailable}/></section>

          <section><h4>Exposure refill</h4><Toggle label="Automatische exposure-refill" description="Versnelt alleen de ontbrekende kant en creëert geen extra capaciteit." checked={quickDraft.exposureRefillEnabled} onChange={(v)=>updateQuick("exposureRefillEnabled",v)} disabled={!exposureAvailable}/>{exposureAvailable&&<div className="v3-grid two"><TimeframeSelect label="LONG snelle timeframe" value={quickDraft.exposureRefillLongTimeframe} onChange={(v)=>updateQuick("exposureRefillLongTimeframe",v)} disabled={!quickDraft.exposureRefillEnabled}/><TimeframeSelect label="SHORT snelle timeframe" value={quickDraft.exposureRefillShortTimeframe} onChange={(v)=>updateQuick("exposureRefillShortTimeframe",v)} disabled={!quickDraft.exposureRefillEnabled}/><Field label="Trigger" value={quickDraft.exposureRefillTriggerPercent} onChange={(v)=>updateQuick("exposureRefillTriggerPercent",v)} suffix="%"/><Field label="Terug naar normaal" value={quickDraft.exposureRefillReleasePercent} onChange={(v)=>updateQuick("exposureRefillReleasePercent",v)} suffix="%"/></div>}</section>

          <section><h4>Bescherming</h4><Toggle label="SHORT alleen met LONG" checked={quickDraft.shortRequiresLongEnabled} onChange={(v)=>updateQuick("shortRequiresLongEnabled",v)}/><Toggle label="Stoploss" checked={quickDraft.stopLossEnabled} onChange={(v)=>updateQuick("stopLossEnabled",v)}/>{quickDraft.stopLossEnabled&&<><label className="v2-field"><span>Stoploss modus</span><select value={quickDraft.stopLossMode} onChange={(e)=>updateQuick("stopLossMode",e.target.value as "PERCENT"|"USD")}><option value="PERCENT">Percentage</option><option value="USD">USDT</option></select></label><div className="v3-grid two"><Field label="Stoploss LONG" value={quickDraft.stopLossLong} onChange={(v)=>updateQuick("stopLossLong",v)} suffix={quickDraft.stopLossMode==="USD"?"USDT":"%"}/><Field label="Stoploss SHORT" value={quickDraft.stopLossShort} onChange={(v)=>updateQuick("stopLossShort",v)} suffix={quickDraft.stopLossMode==="USD"?"USDT":"%"}/></div></>}</section>

          <section><h4>Smart Rescue</h4><Toggle label="Smart Rescue DCA" checked={quickDraft.smartRescueEnabled} onChange={(v)=>updateQuick("smartRescueEnabled",v)}/>{quickDraft.smartRescueEnabled&&<div className="v3-grid two"><Field label="Rescue bereik" value={quickDraft.smartRescueRange} onChange={(v)=>updateQuick("smartRescueRange",v)} suffix="%"/><Field label="Aantal DCA's" value={quickDraft.smartRescueCount} onChange={(v)=>updateQuick("smartRescueCount",v)}/><Field label="Ordergroei" value={quickDraft.smartRescueGrowth} onChange={(v)=>updateQuick("smartRescueGrowth",v)} suffix="x"/><Field label="Herstel" value={quickDraft.smartRescueRecovery} onChange={(v)=>updateQuick("smartRescueRecovery",v)} suffix="%"/></div>}</section>

          <section><h4>Take profit & basis</h4><label className="v2-field"><span>Take profit-modus</span><select value={quickDraft.tpMode} onChange={(e)=>updateQuick("tpMode",e.target.value as TpMode)}><option value="PER_TRADE">Per positie</option><option value="PORTFOLIO">Portfolio</option><option value="OFF">Uit</option></select></label>{quickDraft.tpMode==="PORTFOLIO"&&<><div className="v3-grid two"><label className="v2-field"><span>Doel in</span><select value={quickDraft.portfolioTpInputMode} onChange={(e)=>updateQuick("portfolioTpInputMode",e.target.value as "PERCENT"|"USD")}><option value="PERCENT">Percentage</option><option value="USD">USDT</option></select></label><label className="v2-field"><span>Basis</span><select value={quickDraft.portfolioTpBaseMode} onChange={(e)=>updateQuick("portfolioTpBaseMode",e.target.value as Draft["portfolioTpBaseMode"])}><option value="CYCLE_START">Cycle start</option><option value="CURRENT_VALUE">Huidige waarde</option><option value="CUSTOM">Aangepast</option></select></label></div>{quickDraft.portfolioTpBaseMode==="CUSTOM"&&<Field label="Aangepaste basis" value={quickDraft.portfolioTpCustomBase} onChange={(v)=>updateQuick("portfolioTpCustomBase",v)} suffix="USDT"/>}</>}</section>

          <section className="v31-runtime-rules"><h4>Vaste runtime-regels</h4><p>Alleen lege capaciteit vullen en Auto-restart na TP zijn informatief; hiervoor worden bewust geen fake schakelaars getoond.</p></section>
        </div>}

        <button className="v31-reset" type="button" disabled={!quickDirty||busy} onClick={resetQuickEdit}><QuickIcon name="reset"/> Herstel huidige waarden</button>

        <div className="v31-actions">
          <button className="cancel" type="button" onClick={cancelQuickEdit} disabled={busy}>Annuleren</button>
          <button className="save" type="button" onClick={()=>void saveQuickEdit()} disabled={busy||!quickDirty}>{busy?"Bezig…":"Opslaan"}</button>
        </div>
        {message&&<p className="v31-message">{message}</p>}
      </section>
      <style>{styles}</style>
    </article>;
  }

  return <article id="bot-configurator-v3" className="botconfig-v3" data-version="3.1" data-feature="quick-edit-3.1" data-beta-only="true">
    <header className="v3-top">
      <div className="v3-topline">
        <div><span className="v3-kicker">BOTCONFIGURATOR 3.0</span><h2>Bot configurator</h2><p>Stel je bot snel en duidelijk in.</p></div>
        <div className="v3-top-status">
          {ownerBeta && <span>BETA</span>}
          <b className={enabled ? "on" : ""}>{enabled ? "BOT AAN" : "BOT UIT"}</b>
        </div>
      </div>
      <nav className="v3-progress" aria-label="Botconfigurator stappen">
        {STEP_LABELS.map(([id,label],index) => {
          const step=index+1, done=step<currentStep, active=step===currentStep;
          return <button key={id} type="button" className={active?"active":done?"done":""} onClick={()=>goTo(step)} aria-current={active?"step":undefined}>
            <i>{done?"✓":step}</i><span>{label}</span>
          </button>;
        })}
      </nav>
    </header>

    {currentStep===1 && <section className="v3-screen" data-reference={VISUAL_REFERENCES.strategy}>
      <ScreenTitle title="Kies je strategie" subtitle="Twee handelsstijlen. De exchange staat los van de strategienaam." />
      <div className="v3-strategy-list">
        <button type="button" className={"v3-strategy-card "+(draft.zoneSoldiersEnabled?"selected":"")} onClick={()=>chooseStrategy(true)} disabled={!zoneSoldiersAvailable}>
          <img src="/zone-warriors-icon.svg" alt="" />
          <span><strong>Zone Warriors</strong><small>Handelt per prijszone met een vaste LONG/SHORT-verdeling.</small><em>{zoneSoldiersAvailable?"3 LONG + 3 SHORT per zone":"Nog niet vrijgegeven"}</em></span>
          <i>{draft.zoneSoldiersEnabled?"✓":""}</i>
        </button>
        <button type="button" className={"v3-strategy-card "+(!draft.zoneSoldiersEnabled?"selected":"")} onClick={()=>chooseStrategy(false)}>
          <img src="/classic-dca-icon.svg" alt="" />
          <span><strong>Classic DCA</strong><small>Traditionele strategie met vaste LONG/SHORT-capaciteit en optionele instapfilters en DCA.</small><em>Buy the dip · DCA · flexibel</em></span>
          <i>{!draft.zoneSoldiersEnabled?"✓":""}</i>
        </button>
      </div>
      {zoneLifecycle==="DRAINING" && !draft.zoneSoldiersEnabled && <p className="v3-warning">Bestaande Zone Warriors-posities worden veilig beheerd terwijl nieuwe zone-entries uit staan.</p>}
      <p className="v3-info">Je kiest hier alleen de handelsstrategie. Alle bestaande instellingen blijven in de volgende schermen bereikbaar.</p>
    </section>}

    {currentStep===2 && <section className="v3-screen" data-reference={VISUAL_REFERENCES.settings}>
      <ScreenTitle title="Instellingen" subtitle="Positieverdeling en algemene botinstellingen, compact gegroepeerd." badge={strategyName} />
      {draft.zoneSoldiersEnabled ? <div className="v3-core-settings">
        <h3>Posities per zone</h3>
        <div className="v3-side-pair">
          <StepperField label="LONG per zone" value={draft.zoneLongSeats} onChange={(v)=>update("zoneLongSeats",v)} tone="long" />
          <StepperField label="SHORT per zone" value={draft.zoneShortSeats} onChange={(v)=>update("zoneShortSeats",v)} tone="short" />
        </div>
        <StepperField label="Max totale posities" value={draft.maximumPositions} onChange={(v)=>update("maximumPositions",v)} wide />
        <p className="v3-core-note">Alleen de actieve zone opent nieuwe posities. Bestaande posities blijven gekoppeld aan hun oorspronkelijke zone.</p>
      </div> : <div className="v3-core-settings">
        <h3>LONG / SHORT-capaciteit</h3>
        <div className="v3-side-pair">
          <StepperField label="LONG posities" value={draft.longSlots} onChange={(v)=>update("longSlots",v)} tone="long" />
          <StepperField label="SHORT posities" value={draft.shortSlots} onChange={(v)=>update("shortSlots",v)} tone="short" />
        </div>
        <div className="v3-readonly-row"><span>Max totale posities</span><b>{totals.totalSlots}</b></div>
      </div>}

      <Accordion title="Markt & selectie" icon="▥" open={settingsAccordion==="market"} onToggle={()=>setSettingsAccordion(settingsAccordion==="market"?null:"market")}>
        <div className="v3-grid two">
          <Field label="Top-N volume" value={draft.universeTopN} onChange={(v)=>update("universeTopN",v)} min={1} />
          <Field label="Botnaam" type="text" value={draft.name} onChange={(v)=>update("name",v)} />
        </div>
        <Toggle label="Zelf munten kiezen" description="Uit = automatische Top-N. Aan = alleen jouw selectie." checked={draft.manualEnabled} onChange={(v)=>update("manualEnabled",v)} />
        {draft.manualEnabled && <Field label="Munten · SYMBOL:LONG / SYMBOL:SHORT" type="text" value={draft.manualSymbols} onChange={(v)=>update("manualSymbols",v)} />}
      </Accordion>

      <Accordion title="Leverage" icon="⛓" reference={VISUAL_REFERENCES.leverage} open={settingsAccordion==="leverage"} onToggle={()=>setSettingsAccordion(settingsAccordion==="leverage"?null:"leverage")} summary={`Min ${draft.minimumLeverage}x · Max ${draft.maximumLeverage||"pair max"}`}>
        <div className="v3-grid one">
          <StepperField label="Minimum leverage" value={draft.minimumLeverage} onChange={(v)=>update("minimumLeverage",v)} suffix="x" wide />
          <StepperField label="Maximum leverage" value={draft.maximumLeverage} onChange={(v)=>update("maximumLeverage",v)} suffix="x" wide allowEmpty />
        </div>
        <p className="v3-inline-help">Dit leverage-bereik wordt gebruikt waar de exchange het toestaat.</p>
      </Accordion>

      <Accordion title="Positiegrootte" icon="◉" reference={VISUAL_REFERENCES.positionSize} open={settingsAccordion==="size"} onToggle={()=>setSettingsAccordion(settingsAccordion==="size"?null:"size")} summary="Startbedrag en vaste positieomvang">
        <Toggle label="Vaste positieomvang" description="Uit = bedragen zijn margin. Aan = vaste notional in USDT." checked={draft.fixedPositionSize} onChange={(v)=>update("fixedPositionSize",v)} />
        <div className="v3-side-pair compact">
          <article className="v3-side long"><b>LONG</b><Field label="Startbedrag" value={draft.entryMarginLong} onChange={(v)=>update("entryMarginLong",v)} suffix="USDT" />{draft.fixedPositionSize&&<Field label="Vaste positie" value={draft.entryNotionalLong} onChange={(v)=>update("entryNotionalLong",v)} suffix="USDT" />}</article>
          <article className="v3-side short"><b>SHORT</b><Field label="Startbedrag" value={draft.entryMarginShort} onChange={(v)=>update("entryMarginShort",v)} suffix="USDT" />{draft.fixedPositionSize&&<Field label="Vaste positie" value={draft.entryNotionalShort} onChange={(v)=>update("entryNotionalShort",v)} suffix="USDT" />}</article>
        </div>
        <p className="v3-inline-help">Dit zijn dezelfde startbedragen als op Instap & DCA. Er is één gedeelde configuratiestate.</p>
      </Accordion>
    </section>}

    {currentStep===3 && <section className="v3-screen" data-reference={VISUAL_REFERENCES.entry}>
      <ScreenTitle title="Instap & DCA" subtitle="Instapfilters, startbedragen, DCA en winstname." badge={strategyName} />
      <Accordion title="Instapfilters" icon="≋" open={entryAccordion==="filters"} onToggle={()=>setEntryAccordion(entryAccordion==="filters"?null:"filters")}>
        <Toggle label="Bollinger instapfilter" description="Filtert alleen nieuwe initial entries; DCA blijft apart." checked={draft.bollingerEnabled} onChange={(v)=>update("bollingerEnabled",v)} />
        <div className="v3-grid two">
          <TimeframeSelect label="LONG normaal" value={draft.bollingerLongTimeframe} onChange={(v)=>update("bollingerLongTimeframe",v)} disabled={!draft.bollingerEnabled} />
          <TimeframeSelect label="SHORT normaal" value={draft.bollingerShortTimeframe} onChange={(v)=>update("bollingerShortTimeframe",v)} disabled={!draft.bollingerEnabled||!directionalAvailable} />
          <TimeframeSelect label="Snelle refill LONG" value={draft.exposureRefillLongTimeframe} onChange={(v)=>update("exposureRefillLongTimeframe",v)} disabled={!draft.bollingerEnabled||!exposureAvailable} />
          <TimeframeSelect label="Snelle refill SHORT" value={draft.exposureRefillShortTimeframe} onChange={(v)=>update("exposureRefillShortTimeframe",v)} disabled={!draft.bollingerEnabled||!exposureAvailable} />
        </div>
        <Toggle label="LONG en SHORT apart" description="Iedere richting gebruikt zijn eigen normale timeframe." checked={draft.directionalBollingerEnabled} onChange={(v)=>update("directionalBollingerEnabled",v)} disabled={!directionalAvailable} />
        <Toggle label="Automatische exposure-refill" description="Versnelt alleen de ontbrekende kant en creëert geen extra capaciteit." checked={draft.exposureRefillEnabled} onChange={(v)=>update("exposureRefillEnabled",v)} disabled={!exposureAvailable} />
        {draft.exposureRefillEnabled&&exposureAvailable&&<div className="v3-grid two"><Field label="Versnellen vanaf" value={draft.exposureRefillTriggerPercent} onChange={(v)=>update("exposureRefillTriggerPercent",v)} suffix="%" /><Field label="Normaal onder" value={draft.exposureRefillReleasePercent} onChange={(v)=>update("exposureRefillReleasePercent",v)} suffix="%" /></div>}
      </Accordion>

      <div className="v3-side-pair trading">
        <article className="v3-side long"><h3>↗ LONG</h3>
          <Field label="Startbedrag" value={draft.entryMarginLong} onChange={(v)=>update("entryMarginLong",v)} suffix="USDT" />
          <Field label="DCA-bedrag" value={draft.longDcaAmount} onChange={(v)=>update("longDcaAmount",v)} suffix="USDT" />
          <Field label="DCA-afstand" value={draft.longDcaDistance} onChange={(v)=>update("longDcaDistance",v)} suffix="%" />
          <Field label="Max DCA" value={draft.maxDcaLong} onChange={(v)=>update("maxDcaLong",v)} />
        </article>
        <article className="v3-side short"><h3>↘ SHORT</h3>
          <Field label="Startbedrag" value={draft.entryMarginShort} onChange={(v)=>update("entryMarginShort",v)} suffix="USDT" />
          <Field label="DCA-bedrag" value={draft.shortDcaAmount} onChange={(v)=>update("shortDcaAmount",v)} suffix="USDT" />
          <Field label="DCA-afstand" value={draft.shortDcaDistance} onChange={(v)=>update("shortDcaDistance",v)} suffix="%" />
          <Field label="Max DCA" value={draft.maxDcaShort} onChange={(v)=>update("maxDcaShort",v)} />
        </article>
      </div>

      <div className="v3-tp">
        <div className="v3-tp-head"><b>Take profit</b><div>{(["PER_TRADE","PORTFOLIO","OFF"] as TpMode[]).map(mode=><button key={mode} className={draft.tpMode===mode?"active":""} type="button" onClick={()=>update("tpMode",mode)}>{mode==="PER_TRADE"?"Per trade":mode==="PORTFOLIO"?"Portfolio":"Uit"}</button>)}</div></div>
        {draft.tpMode==="PER_TRADE"&&<div className="v3-grid two"><Field label="TP LONG" value={draft.longTp} onChange={(v)=>update("longTp",v)} suffix="%" /><Field label="TP SHORT" value={draft.shortTp} onChange={(v)=>update("shortTp",v)} suffix="%" /></div>}
        {draft.tpMode==="PORTFOLIO"&&<><div className="v3-grid two"><Field label="Portfolio TP" value={draft.portfolioTpValue} onChange={(v)=>update("portfolioTpValue",v)} suffix={draft.portfolioTpInputMode==="USD"?"USDT":"%"} /><label className="v2-field"><span>Doel in</span><select value={draft.portfolioTpInputMode} onChange={(e)=>update("portfolioTpInputMode",e.target.value as "PERCENT"|"USD")}><option value="PERCENT">Percentage</option><option value="USD">USDT</option></select></label></div><div className="v3-grid two"><label className="v2-field"><span>Basis</span><select value={draft.portfolioTpBaseMode} onChange={(e)=>update("portfolioTpBaseMode",e.target.value as Draft["portfolioTpBaseMode"])}><option value="CYCLE_START">Cycle start</option><option value="CURRENT_VALUE">Huidige waarde</option><option value="CUSTOM">Aangepast</option></select></label>{draft.portfolioTpBaseMode==="CUSTOM"&&<Field label="Aangepaste basis" value={draft.portfolioTpCustomBase} onChange={(v)=>update("portfolioTpCustomBase",v)} suffix="USDT" />}</div></>}
      </div>

      <Accordion title="Smart Rescue DCA" icon="◌" reference={VISUAL_REFERENCES.smartRescue} open={entryAccordion==="rescue"} onToggle={()=>setEntryAccordion(entryAccordion==="rescue"?null:"rescue")}>
        <Toggle label="Smart Rescue DCA" description="Bestaande server-side Smart Rescue-configuratie." checked={draft.smartRescueEnabled} onChange={(v)=>update("smartRescueEnabled",v)} />
        {draft.smartRescueEnabled&&<div className="v3-grid two"><Field label="Rescue bereik" value={draft.smartRescueRange} onChange={(v)=>update("smartRescueRange",v)} suffix="%" /><Field label="Aantal DCA's" value={draft.smartRescueCount} onChange={(v)=>update("smartRescueCount",v)} /><Field label="Ordergroei" value={draft.smartRescueGrowth} onChange={(v)=>update("smartRescueGrowth",v)} suffix="x" /><Field label="Koop na herstel" value={draft.smartRescueRecovery} onChange={(v)=>update("smartRescueRecovery",v)} suffix="%" /></div>}
      </Accordion>

      <Accordion title="Bescherming & exposure" icon="◊" reference={VISUAL_REFERENCES.protection} open={entryAccordion==="protection"} onToggle={()=>setEntryAccordion(entryAccordion==="protection"?null:"protection")}>
        <Toggle label="SHORT alleen met LONG" description="Nieuwe SHORT alleen wanneer dezelfde pair al LONG heeft." checked={draft.shortRequiresLongEnabled} onChange={(v)=>update("shortRequiresLongEnabled",v)} />
        <Toggle label="Stoploss" description="Bestaande server-side reduce-only bescherming." checked={draft.stopLossEnabled} onChange={(v)=>update("stopLossEnabled",v)} />
        {draft.stopLossEnabled&&<><label className="v2-field"><span>Stoploss modus</span><select value={draft.stopLossMode} onChange={(e)=>update("stopLossMode",e.target.value as "PERCENT"|"USD")}><option value="PERCENT">Percentage</option><option value="USD">USDT</option></select></label><div className="v3-grid two"><Field label="Stoploss LONG" value={draft.stopLossLong} onChange={(v)=>update("stopLossLong",v)} suffix={draft.stopLossMode==="USD"?"USDT":"%"} /><Field label="Stoploss SHORT" value={draft.stopLossShort} onChange={(v)=>update("stopLossShort",v)} suffix={draft.stopLossMode==="USD"?"USDT":"%"} /></div></>}
        <div className="v3-runtime-mini"><span>Netto exposure <b>{money(netExposure)}</b></span><span>Onbalans <b>{imbalance.toFixed(1)}%</b></span></div>
      </Accordion>

      <Accordion title="Refill & heropenen" icon="↻" reference={VISUAL_REFERENCES.refill} open={entryAccordion==="refill"} onToggle={()=>setEntryAccordion(entryAccordion==="refill"?null:"refill")}>
        <Toggle label="Automatische exposure-refill" description="Echte bestaande refillfunctie: alleen instaptiming van de ontbrekende kant." checked={draft.exposureRefillEnabled} onChange={(v)=>update("exposureRefillEnabled",v)} disabled={!exposureAvailable} />
        <div className="v3-readonly-list">
          <span><b>Alleen lege capaciteit vullen</b><em>Altijd actief</em></span>
          <span><b>Zone-capaciteit respecteren</b><em>{draft.zoneSoldiersEnabled?"Actief":"n.v.t."}</em></span>
          <span><b>Auto-restart na TP</b><em>Actief · runtime-regel</em></span>
        </div>
        <p className="v3-inline-help">De vaste runtime-regels zijn bewust geen fake schakelaars: ze zijn alleen informatief en worden niet als instelbare optie gepresenteerd.</p>
      </Accordion>
    </section>}

    {currentStep===4 && <section className="v3-screen" data-reference={VISUAL_REFERENCES.review}>
      <ScreenTitle title="Controleren & starten" subtitle="Bekijk alles nog één keer voordat je activeert." />
      <div className="v3-review-hero"><img src={draft.zoneSoldiersEnabled?"/zone-warriors-icon.svg":"/classic-dca-icon.svg"} alt="" /><span><strong>{strategyName}</strong><small>{draft.zoneSoldiersEnabled?"Handelt per prijszone met een vaste verdeling.":"Traditionele DCA met vaste LONG/SHORT-capaciteit."}</small></span></div>
      <div className="v3-review-grid">
        <ReviewBlock title="Posities" rows={[["Verdeling",selectedPositionLabel]]} />
        <ReviewBlock title="Markt & selectie" rows={[["Top-N",draft.universeTopN],["Munten",draft.manualEnabled?"Eigen selectie":"Automatisch"]]} />
        <ReviewBlock title="Leverage" rows={[["Minimum",draft.minimumLeverage+"x"],["Maximum",draft.maximumLeverage?draft.maximumLeverage+"x":"Pair max"]]} />
        <ReviewBlock title="Instapfilters" rows={[["Bollinger",draft.bollingerEnabled?"Aan":"Uit"],["LONG",draft.bollingerLongTimeframe],["SHORT",draft.bollingerShortTimeframe],["Exposure-refill",draft.exposureRefillEnabled?"Aan":"Uit"]]} />
        <ReviewBlock title="Bedragen & DCA" rows={[["Start LONG",draft.entryMarginLong+" USDT"],["Start SHORT",draft.entryMarginShort+" USDT"],["DCA LONG",draft.longDcaAmount+" USDT · "+draft.longDcaDistance+"% · max "+draft.maxDcaLong],["DCA SHORT",draft.shortDcaAmount+" USDT · "+draft.shortDcaDistance+"% · max "+draft.maxDcaShort]]} />
        <ReviewBlock title="Winst" rows={[["Take profit",tpLabel]]} />
        <ReviewBlock title="Bescherming" rows={[["SHORT met LONG",draft.shortRequiresLongEnabled?"Aan":"Uit"],["Stoploss",draft.stopLossEnabled?"Aan":"Uit"]]} />
        <ReviewBlock title="Overig" rows={[["Smart Rescue",draft.smartRescueEnabled?"Aan":"Uit"],["Refill",draft.exposureRefillEnabled?"Aan":"Uit"]]} />
      </div>
      {marginSummaryAvailable&&<div className="v3-capacity"><span><small>Startbelasting</small><b>{money(totals.startMargin)}</b></span><span><small>DCA-capaciteit</small><b>{money(totals.dcaCapacity)}</b></span><span><small>Available</small><b>{available>0?money(available):"—"}</b></span></div>}
      {marginSummaryAvailable&&available>0&&totals.theoretical>available&&<p className="v3-warning">Theoretische volledige belasting is hoger dan huidige available. Dit is een configuratiecheck, geen voorspelling dat alle DCA's tegelijk uitvoeren.</p>}
      <div className="v3-ready"><i>✓</i><span><b>Klaar om te starten</b><small>{serverConfirmed?"Serververbinding bevestigd.":"Wachten op serverbevestiging."} {dirty?"Wijzigingen worden bij de actie opgeslagen.":"Instellingen zijn opgeslagen."}</small></span></div>
    </section>}

    <footer className="v3-nav">
      {currentStep>1?<button className="secondary" type="button" onClick={previous} disabled={busy}>← Vorige</button>:<button className="secondary" type="button" onClick={()=>setMessage("")}>Annuleren</button>}
      {currentStep<4?<button className="primary" type="button" onClick={next}>Volgende →</button>:<button className="primary" type="button" disabled={busy||!serverConfirmed} onClick={bottomAction}>{busy?"Bezig…":enabled?"Instellingen opslaan":"▶ Start bot"}</button>}
      {currentStep===4&&dirty&&<button className="save-only" type="button" disabled={busy} onClick={()=>void save()}>Alleen opslaan</button>}
      {message&&<p>{message}</p>}
    </footer>

    {currentStep===1&&<section className="v31-current" data-reference={VISUAL_REFERENCES.currentSettings} data-source="server-confirmed">
      <header className="v31-current-head">
        <span className="v31-current-title-icon"><QuickIcon name="settings"/></span>
        <div><h3>Huidige instellingen</h3><p>Bekijk je actieve instellingen en pas ze snel aan.</p></div>
        <button type="button" onClick={()=>openQuickEdit()}><QuickIcon name="edit"/> Wijzigen</button>
      </header>
      <div className="v31-current-grid">
        <div className="v31-current-row"><QuickIcon name="layers"/><small>Strategie</small><b>{confirmedStrategyName}</b></div>
        <div className="v31-current-row"><QuickIcon name="dca"/><small>DCA</small><b>LONG {compactUsd(confirmedDraft.longDcaAmount)} / {editableDecimal(confirmedDraft.longDcaDistance)}% / {Math.max(0,Math.round(n(confirmedDraft.maxDcaLong)))}x</b></div>
        <div className="v31-current-row"><QuickIcon name="seats"/><small>Stoelen</small><b>{confirmedSeatLabel}</b></div>
        <div className="v31-current-row"><QuickIcon name="dca"/><small>DCA short</small><b>SHORT {compactUsd(confirmedDraft.shortDcaAmount)} / {editableDecimal(confirmedDraft.shortDcaDistance)}% / {Math.max(0,Math.round(n(confirmedDraft.maxDcaShort)))}x</b></div>
        <div className="v31-current-row"><QuickIcon name="entry"/><small>Instap</small><b>LONG {compactUsd(confirmedDraft.entryMarginLong)} · SHORT {compactUsd(confirmedDraft.entryMarginShort)}</b></div>
        <div className="v31-current-row"><QuickIcon name="target"/><small>TP</small><b>{confirmedTpLabel}</b></div>
        <div className="v31-current-row"><QuickIcon name="leverage"/><small>Leverage</small><b>{confirmedLeverageLabel}</b></div>
        <div className="v31-shortcuts">
          <button type="button" onClick={()=>openQuickEdit("entry")}><QuickIcon name="entry"/> Instap verhogen</button>
          <button type="button" onClick={()=>openQuickEdit("seats")}><QuickIcon name="seats"/> Stoelen aanpassen</button>
        </div>
      </div>
    </section>}

    {ownerBeta&&<details className="v3-release-center">
      <summary>Releasecentrum · BETA-owner</summary>
      <p>Botconfigurator 3.0 gebruikt de bestaande <code>bot_configurator_v2</code>-releasegate. STABLE wordt niet automatisch gewijzigd.</p>
      <div>{Object.entries(releases.features??{}).map(([key,row])=><article key={key}><span><b>{releaseLabel(key)}</b><small>{row.status||"TESTEN"} · BETA {row.beta?"AAN":"UIT"} · STABLE {row.stable?"AAN":"UIT"}</small></span>{key==="price_zones"?<em>IN BOUW</em>:<span>{row.status!=="AKKOORD"&&row.status!=="LIVE"&&<button disabled={busy} onClick={()=>changeRelease(key,{status:"AKKOORD",beta:true,stable:false})}>✓ Getest en akkoord</button>}{row.status==="AKKOORD"&&!row.stable&&<button disabled={busy} onClick={()=>{if(window.confirm(releaseLabel(key)+" vrijgeven aan STABLE?"))void changeRelease(key,{status:"LIVE",beta:true,stable:true,confirm:true})}}>Vrijgeven</button>}{row.stable&&<button disabled={busy} onClick={()=>{if(window.confirm(releaseLabel(key)+" terug naar BETA?"))void changeRelease(key,{status:"TESTEN",beta:true,stable:false,confirm:true})}}>Terug naar BETA</button>}</span>}</article>)}</div>
    </details>}
    <style>{styles}</style>
  </article>;
}

function ScreenTitle({title,subtitle,badge}:{title:string;subtitle:string;badge?:string}){
  return <header className="v3-screen-title"><div><h3>{title}</h3><p>{subtitle}</p></div>{badge&&<span>{badge}</span>}</header>;
}
function Accordion({title,icon,open,onToggle,children,summary,reference}:{title:string;icon:string;open:boolean;onToggle:()=>void;children:ReactNode;summary?:string;reference?:string}){
  return <section className={"v3-accordion "+(open?"open":"")} data-reference={reference}><button type="button" onClick={onToggle} aria-expanded={open}><i>{icon}</i><span><b>{title}</b>{!open&&summary&&<small>{summary}</small>}</span><em>{open?"⌃":"⌄"}</em></button>{open&&<div className="v3-accordion-body">{children}</div>}</section>;
}
function StepperField({label,value,onChange,suffix,wide=false,tone,allowEmpty=false}:{label:string;value:string;onChange:(v:string)=>void;suffix?:string;wide?:boolean;tone?:"long"|"short";allowEmpty?:boolean}){
  const num=n(value,0); const step=(delta:number)=>onChange(String(Math.max(0,Math.round((num+delta)*100)/100)));
  return <label className={"v3-stepper "+(wide?"wide ":"")+(tone||"")}><span>{label}</span><div><button type="button" onClick={()=>step(-1)}>−</button><input inputMode="decimal" value={value} placeholder={allowEmpty?"pair max":undefined} onChange={(e)=>onChange(e.target.value)} /><em>{suffix}</em><button type="button" onClick={()=>step(1)}>+</button></div></label>;
}
function ReviewBlock({title,rows}:{title:string;rows:Array<[string,string]>}){
  return <section className="v3-review-block"><h4>{title}</h4>{rows.map(([label,value])=><span key={label}><small>{label}</small><b>{value}</b></span>)}</section>;
}
function releaseLabel(key: string) {
  return ({ bot_configurator_v2: "Botconfigurator 3.0", directional_bollinger: "Directional Bollinger", exposure_refill: "Exposure refill", margin_summary: "Margin summary", price_zones: "Price zones", zone_soldiers: "Zone Warriors", zone_command_center: "Prijszone-overzicht", auto_hedge_v2: "Auto Hedge 2.0", legacy_hedge_recovery: "Legacy Hedge Recovery" } as Record<string,string>)[key] || key;
}

const styles = `
#bot-configurator-v3{--g:#2be49e;--g2:#13b979;--gold:#d6b458;--red:#ff647f;--bg:#020805;--panel:#06110d;--panel2:#081812;--line:rgba(72,124,101,.38);color:#f2f7f4;background:radial-gradient(circle at 75% 0,rgba(21,143,96,.12),transparent 27%),linear-gradient(180deg,#03100b,#020604);border:1px solid rgba(214,180,88,.28);border-radius:16px;padding:10px;box-shadow:0 20px 55px rgba(0,0,0,.35)}
#bot-configurator-v3 *{box-sizing:border-box}.v3-top{display:grid;gap:10px;padding:2px 2px 8px}.v3-topline{display:flex;align-items:flex-end;justify-content:space-between;gap:8px}.v3-kicker{color:var(--gold);font-size:7px;font-weight:900;letter-spacing:.15em}.v3-top h2{margin:2px 0 0;font-size:21px;line-height:1}.v3-top p{margin:4px 0 0;color:#8fa097;font-size:9px}.v3-top-status{display:flex;align-items:center;gap:5px}.v3-top-status span,.v3-top-status b{border:1px solid rgba(214,180,88,.35);border-radius:999px;padding:4px 6px;font-size:6.5px;letter-spacing:.08em}.v3-top-status span{color:#f0ca61}.v3-top-status b{color:#889990}.v3-top-status b.on{color:#75efbd;border-color:rgba(43,228,158,.44)}
.v3-progress{display:grid;grid-template-columns:repeat(4,1fr);gap:2px;position:relative}.v3-progress:before{content:"";position:absolute;top:13px;left:11%;right:11%;height:1px;background:#31463d}.v3-progress button{position:relative;z-index:1;display:grid;justify-items:center;gap:3px;border:0;background:transparent;color:#788a81;padding:0;font-size:7px}.v3-progress i{display:grid;place-items:center;width:27px;height:27px;border-radius:50%;border:1px solid #43584f;background:#06110d;font-style:normal;font-size:9px}.v3-progress button.active,.v3-progress button.done{color:#69eeb8}.v3-progress button.active i{border-color:var(--g);box-shadow:0 0 12px rgba(43,228,158,.35);color:#a8ffdb}.v3-progress button.done i{background:var(--g2);border-color:var(--g);color:#02120b}
.v3-screen{display:grid;gap:8px;padding:10px 2px 4px;min-height:340px}.v3-screen-title{display:flex;align-items:flex-end;justify-content:space-between;gap:8px;padding:3px 2px 4px}.v3-screen-title h3{margin:0;font-size:18px;line-height:1.05}.v3-screen-title p{margin:4px 0 0;color:#8d9d95;font-size:9px;line-height:1.35}.v3-screen-title>span{max-width:44%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;border:1px solid rgba(43,228,158,.35);border-radius:9px;padding:5px 7px;color:#b6f8dc;background:rgba(13,90,61,.18);font-size:7.5px;font-weight:850}
.v3-strategy-list{display:grid;gap:7px}.v3-strategy-card{display:grid;grid-template-columns:78px minmax(0,1fr) 26px;gap:9px;align-items:center;width:100%;min-height:96px;padding:8px;border:1px solid #31443b;border-radius:13px;background:linear-gradient(120deg,#07120e,#040a07);text-align:left;color:#edf5f1}.v3-strategy-card.selected{border-color:var(--g);box-shadow:inset 0 0 0 1px rgba(43,228,158,.15),0 0 18px rgba(43,228,158,.06)}.v3-strategy-card:disabled{opacity:.5}.v3-strategy-card img{width:78px;height:62px;object-fit:cover;border-radius:9px;background:#04100c}.v3-strategy-card>span{display:grid;gap:3px}.v3-strategy-card strong{font-size:13px}.v3-strategy-card small{color:#a0afa8;font-size:8px;line-height:1.35}.v3-strategy-card em{color:#62dbad;font-size:7px;font-style:normal}.v3-strategy-card>i{display:grid;place-items:center;width:24px;height:24px;border:1px solid #4b5c54;border-radius:50%;font-style:normal}.v3-strategy-card.selected>i{background:var(--g);border-color:var(--g);color:#062016;font-weight:950}.v3-info,.v3-warning{margin:0;padding:8px 9px;border:1px solid rgba(43,228,158,.2);border-radius:10px;background:rgba(8,31,22,.6);color:#9aaba3;font-size:7.5px;line-height:1.4}.v3-warning{border-color:rgba(255,174,88,.36);color:#ffc287;background:rgba(106,56,10,.12)}
.v3-core-settings{display:grid;gap:7px;padding:9px;border:1px solid rgba(43,228,158,.30);border-radius:12px;background:#06130e}.v3-core-settings h3{margin:0;font-size:11px}.v3-core-note{margin:0;padding-top:5px;border-top:1px solid rgba(43,228,158,.12);color:#8fa198;font-size:7.3px;line-height:1.35}.v3-side-pair{display:grid;grid-template-columns:1fr 1fr;gap:7px}.v3-stepper{display:grid;gap:4px;padding:7px;border:1px solid rgba(82,112,98,.32);border-radius:10px;background:#07110e}.v3-stepper>span{font-size:8px;color:#a9b7b0}.v3-stepper>div{display:grid;grid-template-columns:28px minmax(0,1fr) auto 28px;align-items:center;border:1px solid rgba(79,114,98,.32);border-radius:8px;overflow:hidden;background:#030806}.v3-stepper button{height:30px;border:0;background:#0d1a14;color:#68e7b6;font-size:15px}.v3-stepper input{width:100%;height:30px;border:0;outline:0;background:transparent;color:#f3f8f5;text-align:center;font-size:12px;font-weight:850}.v3-stepper em{font-size:7px;color:#84958c;font-style:normal;padding-right:4px}.v3-stepper.long{border-color:rgba(43,228,158,.35)}.v3-stepper.short{border-color:rgba(255,100,127,.35)}.v3-stepper.wide{padding:6px 7px}.v3-readonly-row{display:flex;justify-content:space-between;padding:8px 9px;border:1px solid rgba(79,114,98,.3);border-radius:9px;color:#a8b6af;font-size:8px}.v3-readonly-row b{color:#f2f7f4;font-size:11px}
.v3-accordion{border:1px solid rgba(74,105,91,.42);border-radius:11px;background:#05100c;overflow:hidden}.v3-accordion.open{border-color:rgba(43,228,158,.46);box-shadow:inset 0 0 0 1px rgba(43,228,158,.05)}.v3-accordion>button{display:grid;grid-template-columns:25px minmax(0,1fr) 20px;align-items:center;width:100%;min-height:40px;padding:6px 8px;border:0;background:transparent;color:#f0f6f2;text-align:left}.v3-accordion>button>i{color:#45e4a8;font-size:16px;font-style:normal}.v3-accordion>button>span{display:grid}.v3-accordion>button b{font-size:10px}.v3-accordion>button small{color:#7d8e85;font-size:7px}.v3-accordion>button>em{text-align:center;color:#dfeae4;font-style:normal;font-size:13px}.v3-accordion-body{display:grid;gap:7px;padding:8px;border-top:1px solid rgba(43,228,158,.18);background:linear-gradient(180deg,rgba(6,31,21,.42),rgba(3,12,8,.2))}.v3-inline-help{margin:0;color:#82938a;font-size:7px;line-height:1.4}
.v3-grid{display:grid;gap:6px}.v3-grid.two{grid-template-columns:1fr 1fr}.v3-grid.one{grid-template-columns:1fr}.v2-field{display:grid;gap:3px;color:#abb9b2;font-size:7.5px}.v2-input{display:flex;align-items:center;border:1px solid rgba(83,116,101,.35);border-radius:8px;background:#030906;overflow:hidden}.v2-input input{width:100%;height:32px;border:0;outline:0;background:transparent;color:#f1f7f3;padding:0 8px;font-size:10px}.v2-input em{padding:0 7px;color:#7f9087;font-size:7px;font-style:normal}.v2-field select{width:100%;height:32px;border:1px solid rgba(83,116,101,.35);border-radius:8px;background:#050d09;color:#edf5f1;padding:0 7px;font-size:9px}.v2-field input:disabled,.v2-field select:disabled{opacity:.45}.v2-toggle{display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center;min-height:42px;padding:7px 8px;border:1px solid rgba(79,111,97,.28);border-radius:9px;background:rgba(255,255,255,.012)}.v2-toggle>span{display:grid;gap:1px}.v2-toggle b{font-size:9px}.v2-toggle small{font-size:6.8px;color:#83938b;line-height:1.3}.v2-toggle input{position:absolute;opacity:0}.v2-toggle>i{position:relative;width:36px;height:21px;border-radius:999px;background:#27332e}.v2-toggle>i:after{content:"";position:absolute;width:15px;height:15px;left:3px;top:3px;border-radius:50%;background:#d7e0db;transition:.18s}.v2-toggle.on>i{background:#0c895c;box-shadow:inset 0 0 0 1px #31eba7}.v2-toggle.on>i:after{left:18px;background:#f0fff8}.v2-toggle.disabled{opacity:.48}
.v3-side{display:grid;gap:6px;padding:8px;border-radius:11px;background:#06100c}.v3-side.long{border:1px solid rgba(43,228,158,.46)}.v3-side.short{border:1px solid rgba(255,100,127,.46);background:linear-gradient(140deg,rgba(69,11,23,.18),#06100c)}.v3-side>b,.v3-side h3{margin:0;font-size:10px}.v3-side.long>b,.v3-side.long h3{color:#50eab0}.v3-side.short>b,.v3-side.short h3{color:#ff728a}.v3-side-pair.compact .v3-side{padding:7px}.v3-side-pair.trading .v2-field{grid-template-columns:minmax(0,1fr) minmax(86px,.9fr);align-items:center}.v3-side-pair.trading .v2-input{min-width:0}
.v3-tp{display:grid;gap:7px;padding:8px;border:1px solid rgba(78,113,97,.35);border-radius:11px;background:#06100c}.v3-tp-head{display:flex;align-items:center;justify-content:space-between;gap:6px}.v3-tp-head>b{font-size:9px}.v3-tp-head>div{display:flex;gap:3px}.v3-tp-head button{height:27px;padding:0 8px;border:1px solid rgba(83,116,101,.36);border-radius:7px;background:#0b1511;color:#879890;font-size:7px;font-weight:800}.v3-tp-head button.active{border-color:#d3ad45;background:rgba(121,76,10,.48);color:#ffe7a5}
.v3-runtime-mini{display:grid;grid-template-columns:1fr 1fr;gap:5px}.v3-runtime-mini span{display:flex;justify-content:space-between;padding:7px;border:1px solid rgba(79,112,97,.25);border-radius:8px;color:#879890;font-size:7px}.v3-runtime-mini b{color:#e9f2ed}.v3-readonly-list{display:grid;gap:1px;border:1px solid rgba(80,113,98,.25);border-radius:9px;overflow:hidden}.v3-readonly-list span{display:flex;justify-content:space-between;gap:8px;padding:7px 8px;background:#07110e;font-size:7.5px}.v3-readonly-list em{color:#63ddb0;font-style:normal}
.v3-review-hero{display:grid;grid-template-columns:65px 1fr;gap:8px;align-items:center;padding:7px;border:1px solid rgba(43,228,158,.42);border-radius:11px;background:#06140e}.v3-review-hero img{width:65px;height:48px;object-fit:cover;border-radius:7px}.v3-review-hero span{display:grid}.v3-review-hero strong{font-size:12px}.v3-review-hero small{color:#93a39b;font-size:7.5px}.v3-review-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px}.v3-review-block{display:grid;align-content:start;gap:2px;padding:7px;border:1px solid rgba(70,105,89,.3);border-radius:9px;background:#06100c}.v3-review-block h4{margin:0 0 3px;color:#50e3a8;font-size:8.5px}.v3-review-block span{display:flex;justify-content:space-between;gap:5px;padding:2px 0;border-bottom:1px solid rgba(255,255,255,.035)}.v3-review-block span:last-child{border-bottom:0}.v3-review-block small{color:#819189;font-size:6.5px}.v3-review-block b{max-width:65%;text-align:right;font-size:7px;font-weight:750}.v3-capacity{display:grid;grid-template-columns:repeat(3,1fr);gap:5px}.v3-capacity span{display:grid;padding:7px;border:1px solid rgba(43,228,158,.2);border-radius:8px}.v3-capacity small{font-size:6px;color:#829189}.v3-capacity b{font-size:9px}.v3-ready{display:grid;grid-template-columns:34px 1fr;gap:8px;align-items:center;padding:8px;border:1px solid rgba(43,228,158,.42);border-radius:10px;background:rgba(6,50,33,.45)}.v3-ready>i{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:var(--g);color:#052115;font-style:normal;font-size:15px;font-weight:950}.v3-ready span{display:grid}.v3-ready b{font-size:10px}.v3-ready small{font-size:7px;color:#9aaba3}
.v3-nav{position:sticky;bottom:0;z-index:20;display:grid;grid-template-columns:1fr 1.2fr;gap:7px;padding:8px 2px 4px;background:linear-gradient(0deg,#020604 80%,transparent)}.v3-nav button{height:41px;border-radius:10px;font-size:9px;font-weight:900}.v3-nav .secondary{border:1px solid rgba(91,118,105,.45);background:#0b1310;color:#bdc9c3}.v3-nav .primary{border:1px solid #2ce7a1;background:linear-gradient(180deg,#2bea9f,#12b978);color:#03140d}.v3-nav .save-only{grid-column:1/-1;height:31px;border:1px solid rgba(214,180,88,.35);background:#17140a;color:#e6c76b}.v3-nav p{grid-column:1/-1;margin:0;padding:6px 8px;border:1px solid rgba(81,114,99,.25);border-radius:8px;background:#07110e;color:#b8c4be;font-size:7px}
.v3-release-center{margin-top:8px;border:1px solid rgba(214,180,88,.22);border-radius:10px;padding:7px}.v3-release-center summary{cursor:pointer;color:#d9bd69;font-size:8px;font-weight:850}.v3-release-center>p{color:#7f8f87;font-size:7px}.v3-release-center>div{display:grid;gap:4px}.v3-release-center article{display:flex;justify-content:space-between;align-items:center;gap:6px;padding:6px;border:1px solid rgba(255,255,255,.05);border-radius:8px}.v3-release-center article>span:first-child{display:grid}.v3-release-center b{font-size:7.5px}.v3-release-center small{font-size:6px;color:#74847c}.v3-release-center button{border:1px solid rgba(43,228,158,.3);border-radius:7px;background:#073322;color:#aaf3d4;padding:5px 6px;font-size:6px}.v3-release-center em{color:#d7b961;font-size:6px;font-style:normal}

/* Build 459 · Botconfigurator 3.1 current settings + quick edit */
.v31-icon{width:20px;height:20px;display:block;color:currentColor;flex:0 0 auto}
.v31-current{display:grid;gap:8px;margin:8px 2px 0;padding:10px;border:1px solid rgba(43,228,158,.38);border-radius:14px;background:radial-gradient(circle at 82% 0,rgba(16,142,92,.12),transparent 34%),linear-gradient(180deg,#05130d,#030a07);box-shadow:inset 0 1px rgba(255,255,255,.025),0 0 22px rgba(16,148,95,.05)}
.v31-current-head{display:grid;grid-template-columns:31px minmax(0,1fr) auto;gap:8px;align-items:center}.v31-current-title-icon{display:grid;place-items:center;width:31px;height:31px;color:#e2bb4c}.v31-current-head h3{margin:0;font-size:13px;line-height:1.05}.v31-current-head p{margin:3px 0 0;color:#8fa198;font-size:7.5px}.v31-current-head>button{display:flex;align-items:center;gap:5px;height:34px;padding:0 10px;border:1px solid #20d994;border-radius:9px;background:rgba(6,56,37,.35);color:#54eab1;font-size:8px;font-weight:900}.v31-current-head>button .v31-icon{width:15px;height:15px}
.v31-current-grid{display:grid;grid-template-columns:1fr 1fr;gap:5px}.v31-current-row{display:grid;grid-template-columns:20px 72px minmax(0,1fr);gap:6px;align-items:center;min-width:0;padding:1px 0;background:transparent}.v31-current-row .v31-icon{width:16px;height:16px;color:#38e8a5}.v31-current-row small{color:#94a69d;font-size:7px;white-space:nowrap}.v31-current-row b{min-width:0;padding:5px 6px;border:1px solid rgba(43,228,158,.24);border-radius:7px;background:rgba(7,39,26,.72);color:#edf7f2;font-size:7.2px;font-weight:800;line-height:1.15;white-space:normal;overflow-wrap:anywhere}.v31-current-grid>.v31-current-row:last-child{grid-column:1/2}
.v31-shortcuts{display:grid;grid-template-columns:1fr 1fr;gap:6px}.v31-shortcuts button{display:flex;align-items:center;justify-content:center;gap:5px;min-height:34px;border:1px solid rgba(43,228,158,.36);border-radius:9px;background:#062318;color:#52e9af;font-size:7.5px;font-weight:900}.v31-shortcuts .v31-icon{width:15px;height:15px}
.v31-mode{max-width:900px}.v31-top{display:flex;align-items:flex-end;justify-content:space-between;gap:10px;padding:4px 5px 10px}.v31-top h2{margin:3px 0 0;font-size:22px;line-height:1.04}.v31-top p{margin:5px 0 0;color:#a0afa8;font-size:10px}.v31-quick{display:grid;gap:9px;padding:2px 5px 5px}.v31-info{display:grid;grid-template-columns:28px minmax(0,1fr);gap:9px;align-items:center;padding:10px 12px;border:1px solid rgba(43,228,158,.6);border-radius:12px;background:linear-gradient(120deg,rgba(7,48,33,.9),rgba(3,22,14,.92));color:#d9e7e0}.v31-info .v31-icon{width:24px;height:24px;color:#4deab1}.v31-info p{margin:0;font-size:8.8px;line-height:1.45}
.v31-setting-card{display:grid;grid-template-columns:34px minmax(150px,.8fr) minmax(205px,1fr);gap:10px;align-items:center;padding:11px 12px;border:1px solid rgba(104,132,119,.6);border-radius:13px;background:linear-gradient(120deg,#06120e,#040b08)}.v31-setting-icon{align-self:start;display:grid;place-items:center;width:31px;height:31px;color:#48e8ad}.v31-setting-icon .v31-icon{width:28px;height:28px}.v31-setting-copy h4{margin:0;color:#f0f6f3;font-size:12px}.v31-setting-copy p{margin:3px 0 0;color:#8f9f97;font-size:8px;line-height:1.3}.v31-setting-control{min-width:0}.v31-readonly-value{display:flex;align-items:center;justify-content:center;min-height:38px;border:1px solid rgba(107,130,119,.48);border-radius:9px;background:#101914;color:#b9c5bf;font-size:11px;font-weight:850}
.v31-stepper{display:grid;grid-template-columns:46px minmax(78px,1fr) 46px;min-width:0;border:1px solid rgba(43,228,158,.38);border-radius:10px;overflow:hidden;background:#020905}.v31-stepper>button{height:39px;border:0;background:linear-gradient(180deg,#063521,#042719);color:#43eaae;font-size:18px;font-weight:400}.v31-stepper>button:first-child{border-right:1px solid rgba(43,228,158,.28)}.v31-stepper>button:last-child{border-left:1px solid rgba(43,228,158,.28)}.v31-stepper>label{display:grid;grid-template-columns:auto minmax(38px,1fr) auto;align-items:center;justify-content:center;min-width:0;padding:0 7px;color:#eef8f3}.v31-stepper>label span,.v31-stepper>label em{font-size:12px;font-style:normal;font-weight:850}.v31-stepper input{width:100%;min-width:0;height:37px;padding:0 2px;border:0;outline:0;background:transparent;color:#f4f8f6;text-align:center;font-size:13px;font-weight:900}.v31-stepper.long{border-color:rgba(43,228,158,.5)}.v31-stepper.short{border-color:rgba(255,100,127,.38)}
.v31-sides{display:grid;gap:5px}.v31-sides>div{display:grid;grid-template-columns:76px minmax(0,1fr);gap:7px;align-items:center}.v31-sides b{font-size:9px}.v31-sides b.long{color:#45e5aa}.v31-sides b.short{color:#ff657f}.v31-sides>small{color:#7f9087;text-align:right;font-size:7px}.v31-sides.compact{gap:4px}
.v31-tp-control{display:grid;gap:7px}.v31-segments{display:grid;grid-template-columns:1fr 1fr;border:1px solid rgba(97,124,112,.52);border-radius:10px;overflow:hidden;background:#080f0c}.v31-segments button{height:34px;border:0;background:transparent;color:#b2beb8;font-size:8.5px;font-weight:800}.v31-segments button.active{background:linear-gradient(180deg,#08764e,#065235);color:#f0fff8;box-shadow:inset 0 0 0 1px #31eaa7}.v31-off-label{color:#c8a854;font-size:7px}
.v31-more{display:flex;align-items:center;gap:8px;width:100%;min-height:40px;padding:0 12px;border:1px solid rgba(43,228,158,.5);border-radius:11px;background:#06180f;color:#e0e9e4;text-align:left;font-size:9px}.v31-more span{font-size:15px}.v31-more.open{border-color:rgba(43,228,158,.75)}
.v31-advanced{display:grid;gap:8px;padding:9px;border:1px solid rgba(43,228,158,.24);border-radius:12px;background:#04100b}.v31-advanced>section{display:grid;gap:7px;padding:8px;border:1px solid rgba(83,116,101,.28);border-radius:10px;background:#06110d}.v31-advanced h4{margin:0;color:#57e8ae;font-size:9.5px}.v31-runtime-rules p{margin:0;color:#82938a;font-size:7.3px;line-height:1.4}
.v31-reset{display:flex;align-items:center;justify-content:center;gap:7px;min-height:38px;border:1px solid rgba(112,137,125,.56);border-radius:10px;background:#07110d;color:#aebcb5;font-size:8.5px}.v31-reset .v31-icon{width:17px;height:17px}.v31-reset:disabled{opacity:.42}
.v31-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px}.v31-actions button{height:46px;border-radius:11px;font-size:10px;font-weight:900}.v31-actions .cancel{border:1px solid rgba(116,139,128,.56);background:linear-gradient(180deg,#26322d,#1b2420);color:#aab5af}.v31-actions .save{border:1px solid #31e9a8;background:linear-gradient(180deg,#078e5c,#056c45);color:#f4fff9}.v31-actions .save:disabled{opacity:.45}.v31-message{margin:0;padding:7px 9px;border:1px solid rgba(43,228,158,.22);border-radius:8px;background:#07120e;color:#b7c7bf;font-size:7.5px}

@media(max-width:430px){#bot-configurator-v3{padding:8px;border-radius:14px;overflow:hidden}.v31-current{margin-left:0;margin-right:0}.v31-setting-card{grid-template-columns:28px minmax(68px,.48fr) minmax(188px,1.25fr);gap:6px;padding:9px}.v31-setting-icon{grid-row:auto}.v31-setting-copy{grid-column:auto}.v31-setting-control{grid-column:auto}.v31-setting-card.rows{grid-template-columns:28px minmax(0,1fr);grid-template-rows:auto auto}.v31-setting-card.rows .v31-setting-icon{grid-row:1/3}.v31-setting-card.rows .v31-setting-copy{grid-column:2}.v31-setting-card.rows .v31-setting-control{grid-column:2}.v31-setting-card.rows .v31-sides>div{grid-template-columns:72px minmax(0,1fr)}.v31-current-grid{grid-template-columns:1fr 1fr}.v31-current-row{grid-template-columns:17px 58px minmax(0,1fr);padding:6px 5px;gap:4px}.v31-current-row b{font-size:6.8px}.v31-current-row small{font-size:6.4px}.v31-current-head{grid-template-columns:28px minmax(0,1fr) auto}.v31-current-head>button{padding:0 8px}.v31-sides>div{grid-template-columns:50px minmax(0,1fr);gap:6px}.v31-stepper{grid-template-columns:36px minmax(58px,1fr) 36px}.v31-top h2{font-size:20px}.v31-quick{padding-left:2px;padding-right:2px}.v3-screen{padding-top:7px}.v3-strategy-card{grid-template-columns:70px minmax(0,1fr) 24px;min-height:88px}.v3-strategy-card img{width:70px;height:55px}.v3-grid.two,.v3-side-pair,.v3-review-grid{grid-template-columns:1fr 1fr}.v3-side-pair.trading .v2-field{grid-template-columns:1fr}.v3-tp-head{align-items:flex-start}.v3-tp-head>div{flex-wrap:wrap;justify-content:flex-end}.v3-review-block b{max-width:62%}}
@media(max-width:350px){.v31-current-grid{grid-template-columns:1fr}.v31-setting-card{grid-template-columns:28px minmax(0,1fr)}.v31-setting-card.rows{grid-template-columns:28px minmax(0,1fr)}.v31-setting-card.rows .v31-sides>div{grid-template-columns:62px minmax(0,1fr)}.v31-setting-icon{grid-row:1/3}.v31-setting-copy{grid-column:2}.v31-setting-control{grid-column:1/-1}.v31-shortcuts{grid-template-columns:1fr 1fr}.v31-current-grid>.v31-current-row:last-child{grid-column:auto}.v31-current-row{grid-template-columns:18px 66px minmax(0,1fr)}.v31-setting-card{padding:9px}.v31-sides>div{grid-template-columns:62px minmax(0,1fr)}.v31-stepper{grid-template-columns:40px minmax(64px,1fr) 40px}.v31-info{grid-template-columns:24px minmax(0,1fr);padding:9px}.v31-info .v31-icon{width:20px;height:20px}.v3-side-pair,.v3-grid.two,.v3-review-grid{grid-template-columns:1fr}.v3-strategy-card{grid-template-columns:60px minmax(0,1fr) 22px}.v3-strategy-card img{width:60px;height:48px}}
`;
