"use client";

import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { strategy2ServerStatus } from "@/lib/aster-strategy2-server-status.mjs";
import { MAX_SIDE_SLOTS, MAX_TOTAL_POSITIONS, applyLongSlots, applyShortSlots, splitTotalPositions } from "@/lib/position-slot-input";

type ManualSide = "LONG" | "SHORT";
type ManualSymbol = { symbol: string; side: ManualSide };
type TpMode = "PER_TRADE" | "PORTFOLIO" | "OFF";
type PortfolioTpInputMode = "PERCENT" | "USD";
type PortfolioTpBaseMode = "CYCLE_START" | "CURRENT_VALUE" | "CUSTOM";
type StopLossMode = "USD" | "PERCENT";
const BOT_SETTINGS_REFERENCE = "file_00000000d2ec81f4b0c6fe6b9befe97c";
const PORTFOLIO_TP_REFERENCE = "file_00000000f6e08210b726c694adc15111";
type TierPreview = {
  symbol: string;
  entryPlan?: { leverage: number } | null;
  currentLeverage?: number;
  minimumEntryMarginUsd?: number;
  suggestedEntryMarginUsd?: number;
  configuredEntryMarginUsd?: number;
  entryOrderValid?: boolean;
};
type Values = {
  name: string; universe: string; positions: string; longSlots: string; shortSlots: string; minLeverage: string; maxLeverage: string;
  stopLossEnabled: boolean; stopLossMode: StopLossMode; stopLossLong: string; stopLossShort: string;
  fixedPositionSize: boolean;
  entryMarginLong: string; entryMarginShort: string; entryNotionalLong: string; entryNotionalShort: string;
  longDcaDistance: string; shortDcaDistance: string; longDcaAmount: string; shortDcaAmount: string;
  maxDcaLong: string; maxDcaShort: string; longTp: string; shortTp: string; tpMode: TpMode; portfolioTp: string;
  portfolioTpInputMode: PortfolioTpInputMode; portfolioTpBaseMode: PortfolioTpBaseMode; portfolioTpCustomBase: string;
  mode: "paper" | "live"; manualEnabled: boolean; manualSymbols: ManualSymbol[]; shortRequiresLongEnabled: boolean;
  smartRescueEnabled: boolean; smartRescueRange: string; smartRescueCount: string; smartRescueGrowth: string; smartRescueRecovery: string;
};

const initial: Values = {
  name: "Aster Multi DCA", universe: "30", positions: "30", longSlots: "20", shortSlots: "10", minLeverage: "50", maxLeverage: "",
  stopLossEnabled: false, stopLossMode: "PERCENT", stopLossLong: "5", stopLossShort: "5",
  fixedPositionSize: false, entryMarginLong: "5", entryMarginShort: "5", entryNotionalLong: "250", entryNotionalShort: "250",
  longDcaDistance: "0.30", shortDcaDistance: "0.30",
  longDcaAmount: "2", shortDcaAmount: "2", maxDcaLong: "3", maxDcaShort: "3", longTp: "1.5", shortTp: "1.5",
  tpMode: "PER_TRADE", portfolioTp: "20", portfolioTpInputMode: "PERCENT", portfolioTpBaseMode: "CYCLE_START", portfolioTpCustomBase: "",
  mode: "live", manualEnabled: false, manualSymbols: [], shortRequiresLongEnabled: false,
  smartRescueEnabled: false, smartRescueRange: "10", smartRescueCount: "10", smartRescueGrowth: "1.35", smartRescueRecovery: "0.30",
};
const MAX_DCA = 500;
const n = (value: string) => Number(value.replace(",", ".")) || 0;
const clampInt = (value: number, min: number, max: number) => Math.max(min, Math.min(max, Math.round(value || 0)));
const pct = (value: unknown, fallback: number) => String((Number.isFinite(Number(value)) ? Number(value) : fallback) * 100);
const txt = (value: unknown, fallback: number) => String(Number.isFinite(Number(value)) ? Number(value) : fallback);
const parseManualSymbols = (value: unknown): ManualSymbol[] => Array.isArray(value) ? value.flatMap((row) => {
  if (!row || typeof row !== "object") return [];
  const item = row as Record<string, unknown>; const symbol = String(item.symbol || "").toUpperCase(); const side = String(item.side || "").toUpperCase();
  return symbol && (side === "LONG" || side === "SHORT") ? [{ symbol, side: side as ManualSide }] : [];
}) : [];
const tpModeFrom = (x: Record<string, unknown>): TpMode => {
  const raw = String(x.takeProfitMode || (x.takeProfitEnabled === false ? "OFF" : "PER_TRADE")).toUpperCase();
  return raw === "PORTFOLIO" ? "PORTFOLIO" : raw === "OFF" ? "OFF" : "PER_TRADE";
};
const portfolioTpInputModeFrom = (value: unknown): PortfolioTpInputMode => String(value || "PERCENT").toUpperCase().replace("%", "PERCENT").replace("$", "USD") === "USD" ? "USD" : "PERCENT";
const portfolioTpBaseModeFrom = (value: unknown): PortfolioTpBaseMode => {
  const raw = String(value || "CYCLE_START").toUpperCase().replaceAll("-", "_").replaceAll(" ", "_");
  return raw === "CURRENT_VALUE" ? "CURRENT_VALUE" : raw === "CUSTOM" ? "CUSTOM" : "CYCLE_START";
};
const portfolioTarget = (base: number, mode: PortfolioTpInputMode, value: number) => base > 0 && value > 0 ? mode === "USD" ? base + value : base * (1 + value / 100) : 0;
const money2 = (value: number) => Number.isFinite(value) && value > 0 ? value.toLocaleString("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—";

type SmartPreviewRow = {
  index: number; drop: number; trigger: number; orderMargin: number; cumulativeMargin: number; notional: number; averageEntry: number; pnl: number; breakEven: number; recovery: number; capped: boolean;
};
const MAX_PREVIEW_MONEY = 1e15;
const finiteOr = (value: unknown, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
function smartOrderMargin(start: number, growth: number, index: number) {
  if (!(start > 0) || !(growth >= 1) || index < 1) return { value: 0, capped: false };
  const logValue = Math.log(start) + index * Math.log(growth);
  const capped = logValue > Math.log(MAX_PREVIEW_MONEY);
  return { value: capped ? MAX_PREVIEW_MONEY : Math.exp(logValue), capped };
}
function buildSmartPreview(startMargin: number, leverage: number, range: number, count: number, growth: number) {
  const initialPrice = 100; const rows: SmartPreviewRow[] = [];
  let totalMargin = Math.max(0, startMargin); let totalNotional = totalMargin * Math.max(1, leverage); let totalQty = totalNotional / initialPrice; let capped = false;
  const safeCount = Math.max(1, Math.min(MAX_DCA, Math.round(count || 1)));
  for (let index = 1; index <= safeCount; index += 1) {
    const drop = index === safeCount ? range : range * Math.pow(index / safeCount, 1.5);
    const trigger = initialPrice * (1 - drop / 100);
    const order = smartOrderMargin(startMargin, growth, index); capped ||= order.capped;
    const orderMargin = order.value; const orderNotional = orderMargin * Math.max(1, leverage); const qty = trigger > 0 ? orderNotional / trigger : 0;
    totalMargin = Math.min(MAX_PREVIEW_MONEY, totalMargin + orderMargin); totalNotional = Math.min(MAX_PREVIEW_MONEY, totalNotional + orderNotional); totalQty += qty;
    const averageEntry = totalQty > 0 ? totalNotional / totalQty : initialPrice; const pnl = totalQty * (trigger - averageEntry); const recovery = trigger > 0 ? (averageEntry / trigger - 1) * 100 : 0;
    rows.push({ index, drop, trigger, orderMargin, cumulativeMargin: totalMargin, notional: totalNotional, averageEntry, pnl, breakEven: averageEntry, recovery, capped: capped || totalMargin >= MAX_PREVIEW_MONEY || totalNotional >= MAX_PREVIEW_MONEY });
  }
  const last = rows.at(-1); return { rows, maxMargin: totalMargin, finalBreakEven: last?.breakEven ?? initialPrice, finalRecovery: last?.recovery ?? 0, finalPrice: last?.trigger ?? initialPrice, capped };
}
function money(value: number) { return Number.isFinite(value) ? `$${value >= 1000000 ? value.toLocaleString("nl-NL", { maximumFractionDigits: 0 }) : value.toFixed(value < 10 ? 2 : 0)}` : "—"; }

export function AsterStrategy2Maker({ snapshot, serverConfirmed, onConfirmed, onChanged }: { snapshot: Record<string, unknown> | null; serverConfirmed: boolean; onConfirmed: (strategy2: Record<string, unknown>) => void; onChanged: () => void }) {
  const [v, setV] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [dirty, setDirty] = useState(false);
  const [readiness, setReadiness] = useState<Record<string, unknown> | null>(null);
  const [confirmedState, setConfirmedState] = useState<Record<string, unknown> | null>(null);
  const [markets, setMarkets] = useState<string[]>([]);
  const [marketSearch, setMarketSearch] = useState("");
  const [marketBusy, setMarketBusy] = useState(false);
  const [marketAttempted, setMarketAttempted] = useState(false);
  const [marketLoadError, setMarketLoadError] = useState("");
  const [tierPreviews, setTierPreviews] = useState<Record<string, TierPreview>>({});
  const [tierBusy, setTierBusy] = useState(false);
  const [totalDraft, setTotalDraft] = useState<string | null>(null);
  const [longDraft, setLongDraft] = useState<string | null>(null);
  const [shortDraft, setShortDraft] = useState<string | null>(null);

  const snapshotState = (snapshot?.strategy2 && typeof snapshot.strategy2 === "object" ? snapshot.strategy2 : {}) as Record<string, unknown>;
  const status = strategy2ServerStatus(snapshotState, confirmedState, serverConfirmed);
  const state = status.state as Record<string, unknown>;
  const persisted = (state.settings && typeof state.settings === "object" ? state.settings : {}) as Record<string, unknown>;
  const rawReport = ((state.multiBb && typeof state.multiBb === "object" ? state.multiBb : state.multiBbReport && typeof state.multiBbReport === "object" ? state.multiBbReport : {}) || {}) as Record<string, unknown>;
  const cycle = (rawReport.portfolioCycle && typeof rawReport.portfolioCycle === "object" ? rawReport.portfolioCycle : {}) as Record<string, unknown>;

  useEffect(() => {
    if (dirty) return;
    const x = persisted;
    if (!x || String(x.engine || x.strategyKind) !== "multi_bb_v1") return;
    const longSlots = clampInt(Number(x.longSlots ?? 20), 0, MAX_SIDE_SLOTS); const shortSlots = clampInt(Number(x.shortSlots ?? 10), 0, MAX_SIDE_SLOTS);
    const legacyEntry = Number(x.entryMarginUsd ?? 5);
    const persistedMinLeverage = Math.max(1, Number(x.minimumLeverage ?? 50));
    const legacyLongMargin = Number(x.entryMarginLongUsd ?? x.entryMarginLong ?? legacyEntry);
    const legacyShortMargin = Number(x.entryMarginShortUsd ?? x.entryMarginShort ?? legacyEntry);
    const legacyLongNotional = Number(x.entryNotionalLongUsd ?? x.entryNotionalLong ?? x.entryNotionalUsd ?? legacyLongMargin * persistedMinLeverage);
    const legacyShortNotional = Number(x.entryNotionalShortUsd ?? x.entryNotionalShort ?? legacyShortMargin * persistedMinLeverage);
    const legacyDcaDistance = Number(x.dcaDistance ?? .003); const legacyDcaAmount = Number(x.dcaMarginUsd ?? 2); const legacyMax = Number(x.maxDca ?? 3); const legacyTp = Number(x.takeProfit ?? .015);
    setV({
      name: String(x.name || initial.name), universe: String(x.universeTopN ?? 30), positions: String(Math.min(MAX_TOTAL_POSITIONS, longSlots + shortSlots)), longSlots: String(longSlots), shortSlots: String(shortSlots), minLeverage: String(x.minimumLeverage ?? 50), maxLeverage: x.maximumLeverage === null || x.maximumLeverage === undefined ? "" : String(x.maximumLeverage),
      stopLossEnabled: x.stopLossEnabled === true, stopLossMode: String(x.stopLossMode || "PERCENT").toUpperCase() === "USD" ? "USD" : "PERCENT", stopLossLong: txt(x.stopLossLong, 5), stopLossShort: txt(x.stopLossShort, 5),
      fixedPositionSize: String(x.entrySizingMode || "margin").toLowerCase() === "notional",
      entryMarginLong: txt(legacyLongMargin, legacyEntry), entryMarginShort: txt(legacyShortMargin, legacyEntry),
      entryNotionalLong: txt(legacyLongNotional, legacyEntry * persistedMinLeverage), entryNotionalShort: txt(legacyShortNotional, legacyEntry * persistedMinLeverage),
      longDcaDistance: pct(x.longDcaDistance ?? legacyDcaDistance, legacyDcaDistance), shortDcaDistance: pct(x.shortDcaDistance ?? legacyDcaDistance, legacyDcaDistance),
      longDcaAmount: txt(x.longDcaMarginUsd ?? x.longDcaAmount ?? legacyDcaAmount, legacyDcaAmount), shortDcaAmount: txt(x.shortDcaMarginUsd ?? x.shortDcaAmount ?? legacyDcaAmount, legacyDcaAmount),
      maxDcaLong: txt(x.maxDcaLong ?? x.longMaxDca ?? legacyMax, legacyMax), maxDcaShort: txt(x.maxDcaShort ?? x.shortMaxDca ?? legacyMax, legacyMax),
      longTp: pct(x.longTakeProfitValue ?? x.takeProfitLong ?? legacyTp, legacyTp), shortTp: pct(x.shortTakeProfitValue ?? x.takeProfitShort ?? legacyTp, legacyTp),
      tpMode: tpModeFrom(x),
      portfolioTp: txt(x.portfolioTpValue ?? x.portfolioTpPercent, 20),
      portfolioTpInputMode: portfolioTpInputModeFrom(x.portfolioTpInputMode),
      portfolioTpBaseMode: portfolioTpBaseModeFrom(x.portfolioTpBaseMode),
      portfolioTpCustomBase: Number(x.portfolioTpCustomBaseEquity ?? 0) > 0 ? txt(x.portfolioTpCustomBaseEquity, 0) : "",
      mode: x.mode === "paper" ? "paper" : "live",
      manualEnabled: x.manualSymbolSelectionEnabled === true, manualSymbols: parseManualSymbols(x.manualSymbols),
      shortRequiresLongEnabled: x.shortRequiresLongEnabled === true,
      smartRescueEnabled: x.smartRescueEnabled === true, smartRescueRange: txt(x.smartRescueRangePercent, 10),
      smartRescueCount: txt(x.smartRescueDcaCount, 10), smartRescueGrowth: txt(x.smartRescueOrderGrowthMultiplier, 1.35),
      smartRescueRecovery: txt(x.smartRescueTrailingRecoveryPercent, .30),
    });
    setTotalDraft(null);
    setLongDraft(null);
    setShortDraft(null);
  }, [persisted, dirty]);

  const change = (next: Values) => { setV(next); setDirty(true); setMessage(""); };
  const settings = (() => {
    const longSlots = clampInt(n(v.longSlots), 0, MAX_SIDE_SLOTS); const shortSlots = clampInt(n(v.shortSlots), 0, MAX_SIDE_SLOTS); const minLeverage = Math.max(1, Math.round(n(v.minLeverage)));
    const maxLeverageText = v.maxLeverage.trim(); const maxLeverage = maxLeverageText ? Math.max(1, Math.round(n(maxLeverageText))) : null;
    const longEntry = n(v.entryMarginLong); const shortEntry = n(v.entryMarginShort);
    const longNotional = n(v.entryNotionalLong); const shortNotional = n(v.entryNotionalShort);
    const longDistance = n(v.longDcaDistance) / 100; const shortDistance = n(v.shortDcaDistance) / 100;
    const longAmount = n(v.longDcaAmount); const shortAmount = n(v.shortDcaAmount); const maxLong = clampInt(n(v.maxDcaLong), 0, MAX_DCA); const maxShort = clampInt(n(v.maxDcaShort), 0, MAX_DCA);
    const longTp = n(v.longTp) / 100; const shortTp = n(v.shortTp) / 100;
    return {
      ...persisted,
      engine: "multi_bb_v1", strategyKind: "multi_bb_v1", name: v.name, mode: v.mode, universeTopN: Math.max(1, Math.round(n(v.universe))),
      maximumPositions: Math.min(MAX_TOTAL_POSITIONS, longSlots + shortSlots), longSlots, shortSlots, minimumLeverage: minLeverage, maximumLeverage: maxLeverage,
      entrySizingMode: v.fixedPositionSize ? "notional" : "margin",
      entryMarginUsd: longEntry, entryMarginLongUsd: longEntry, entryMarginShortUsd: shortEntry, entryMarginLong: longEntry, entryMarginShort: shortEntry,
      entryNotionalUsd: longNotional, entryNotionalLongUsd: longNotional, entryNotionalShortUsd: shortNotional, entryNotionalLong: longNotional, entryNotionalShort: shortNotional,
      dcaDistance: longDistance, longDcaDistance: longDistance, shortDcaDistance: shortDistance,
      dcaMarginUsd: longAmount, longDcaMarginUsd: longAmount, shortDcaMarginUsd: shortAmount, longDcaAmount: longAmount, shortDcaAmount: shortAmount,
      maxDca: maxLong, maxDcaLong: maxLong, maxDcaShort: maxShort, longMaxDca: maxLong, shortMaxDca: maxShort, unlimitedDca: false,
      takeProfit: longTp, longTakeProfitValue: longTp, shortTakeProfitValue: shortTp, takeProfitLong: longTp, takeProfitShort: shortTp,
      takeProfitMode: v.tpMode,
      portfolioTpPercent: v.portfolioTpInputMode === "PERCENT" ? n(v.portfolioTp) : finiteOr(persisted.portfolioTpPercent, 20),
      portfolioTpInputMode: v.portfolioTpInputMode,
      portfolioTpValue: n(v.portfolioTp),
      portfolioTpBaseMode: v.portfolioTpBaseMode,
      portfolioTpCustomBaseEquity: n(v.portfolioTpCustomBase),
      takeProfitEnabled: v.tpMode === "PER_TRADE",
      stopLossEnabled: v.stopLossEnabled, stopLossMode: v.stopLossMode, stopLossLong: n(v.stopLossLong), stopLossShort: n(v.stopLossShort),
      entryMode: "immediate_fill", marginMode: "cross", autoRestart: true,
      manualSymbolSelectionEnabled: v.manualEnabled, manualSymbols: v.manualEnabled ? v.manualSymbols : [],
      shortRequiresLongEnabled: v.shortRequiresLongEnabled,
      // Asymmetric hedge remains a legacy/runtime capability but has no control
      // in normal Botinstellingen. Never carry an invisible stale paired-entry
      // mode forward when the user saves, simulates or starts normal Multi DCA.
      asymmetricHedgeModeEnabled: false,
      smartRescueEnabled: v.smartRescueEnabled, smartRescueVersion: 1, smartRescueRangePercent: n(v.smartRescueRange),
      smartRescueDcaCount: Math.round(n(v.smartRescueCount)), smartRescueOrderGrowthMultiplier: n(v.smartRescueGrowth),
      smartRescueTrailingRecoveryPercent: n(v.smartRescueRecovery), smartRescuePrimarySide: v.smartRescueEnabled ? "LONG" : null,
    };
  })();

  const setTotal = (raw: string) => {
    const slots = splitTotalPositions(raw);
    change({ ...v, positions: String(slots.total), longSlots: String(slots.long), shortSlots: String(slots.short) });
  };
  const commitTotal = () => { const raw = String(totalDraft ?? v.positions).trim(); setTotalDraft(null); if (raw) setTotal(raw); };
  const setLong = (raw: string) => {
    const slots = applyLongSlots(v.positions, raw);
    change({ ...v, positions: String(slots.total), longSlots: String(slots.long), shortSlots: String(slots.short) });
  };
  const commitLong = () => { const raw = String(longDraft ?? v.longSlots).trim(); setLongDraft(null); if (raw) setLong(raw); };
  const setShort = (raw: string) => {
    const slots = applyShortSlots(v.positions, raw);
    change({ ...v, positions: String(slots.total), longSlots: String(slots.long), shortSlots: String(slots.short) });
  };
  const commitShort = () => { const raw = String(shortDraft ?? v.shortSlots).trim(); setShortDraft(null); if (raw) setShort(raw); };

  async function loadMarkets() {
    if (marketBusy) return; setMarketAttempted(true); setMarketBusy(true); setMarketLoadError("");
    try {
      const result = await authenticatedRequest("/api/exchanges/aster/strategy2/focus/markets") as Record<string, unknown>;
      if (!Array.isArray(result.ranking)) throw new Error("Aster-marktlijst gaf geen geldige ranking terug.");
      const symbols = result.ranking.flatMap((row) => row && typeof row === "object" ? [String((row as Record<string, unknown>).symbol || "").toUpperCase().trim()] : []).filter(Boolean);
      if (!symbols.length) throw new Error("Aster retourneerde geen actieve USDT perpetuals.");
      setMarkets([...new Set(symbols)]);
    }
    catch (error) { const text = error instanceof Error ? error.message : "Aster-markten konden niet worden geladen."; setMarketLoadError(text); setMessage(text); }
    finally { setMarketBusy(false); }
  }
  useEffect(() => { if (v.manualEnabled && !marketAttempted) void loadMarkets(); }, [v.manualEnabled, marketAttempted]);
  useEffect(() => {
    if (!v.manualEnabled || !v.manualSymbols.length) { setTierPreviews({}); return; }
    let cancelled = false; setTierBusy(true);
    void Promise.all(v.manualSymbols.map(async (row) => {
      const entryMargin = row.side === "SHORT" ? v.entryMarginShort : v.entryMarginLong; const entryNotional = row.side === "SHORT" ? v.entryNotionalShort : v.entryNotionalLong; const dca = row.side === "SHORT" ? v.shortDcaAmount : v.longDcaAmount;
      const query: Record<string, string> = { symbol: row.symbol, minimumLeverage: String(Math.max(1, Math.round(n(v.minLeverage)))), entrySizingMode: v.fixedPositionSize ? "notional" : "margin", dcaMarginUsd: String(Math.max(.01, n(dca))) };
      if (v.fixedPositionSize) query.entryNotionalUsd = String(Math.max(.01, n(entryNotional))); else query.entryMarginUsd = String(Math.max(.01, n(entryMargin)));
      if (v.maxLeverage.trim()) query.maximumLeverage = String(Math.max(1, Math.round(n(v.maxLeverage)))); const q = new URLSearchParams(query);
      const result = await authenticatedRequest(`/api/exchanges/aster/strategy2/leverage-tiers?${q.toString()}`) as TierPreview; return [row.symbol, result] as const;
    })).then((rows) => { if (!cancelled) setTierPreviews(Object.fromEntries(rows)); }).catch((error) => { if (!cancelled) setMessage(error instanceof Error ? error.message : "Leverage tiers konden niet worden geladen."); }).finally(() => { if (!cancelled) setTierBusy(false); });
    return () => { cancelled = true; };
  }, [v.manualEnabled, v.manualSymbols, v.minLeverage, v.maxLeverage, v.fixedPositionSize, v.entryMarginLong, v.entryMarginShort, v.entryNotionalLong, v.entryNotionalShort, v.longDcaAmount, v.shortDcaAmount]);

  const selected = new Set(v.manualSymbols.map((row) => row.symbol));
  const marketQuery = marketSearch.trim().toUpperCase();
  const marketMatches = markets.filter((symbol) => !selected.has(symbol) && symbol.includes(marketQuery)).slice(0, 12);
  const directMarket = markets.find((symbol) => !selected.has(symbol) && (symbol === marketQuery || symbol === `${marketQuery}USDT`)) || (marketMatches.length === 1 ? marketMatches[0] : "");
  const addSymbol = (symbol: string) => { if (!symbol || selected.has(symbol)) return; change({ ...v, manualSymbols: [...v.manualSymbols, { symbol, side: "LONG" }] }); setMarketSearch(""); };
  const setSymbolSide = (symbol: string, side: ManualSide) => change({ ...v, manualSymbols: v.manualSymbols.map((row) => row.symbol === symbol ? { ...row, side } : row) });
  const removeSymbol = (symbol: string) => change({ ...v, manualSymbols: v.manualSymbols.filter((row) => row.symbol !== symbol) });

  async function withLatestProfitLockSettings(draft: Record<string, unknown>) {
    // Profit Lock is edited by its own bridge. A stale maker snapshot must never
    // turn it off, restore old levels, or alter its primary-side marker when a
    // normal Bot Settings save/start happens afterwards.
    const latest = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" }) as Record<string, unknown>;
    const latestStrategy2 = latest.strategy2 && typeof latest.strategy2 === "object" ? latest.strategy2 as Record<string, unknown> : {};
    const latestSettings = latestStrategy2.settings && typeof latestStrategy2.settings === "object" ? latestStrategy2.settings as Record<string, unknown> : {};
    const merged = { ...draft };
    for (const key of ["profitLockLadderEnabled", "profitLockLevels", "profitLockPrimarySide"] as const) {
      if (Object.prototype.hasOwnProperty.call(latestSettings, key)) merged[key] = latestSettings[key];
    }
    return merged;
  }

  async function action(kind: "save" | "simulate" | "start" | "stop") {
    setBusy(true); setMessage("");
    try {
      if (settings.longSlots + settings.shortSlots < 1 || settings.longSlots > MAX_SIDE_SLOTS || settings.shortSlots > MAX_SIDE_SLOTS || settings.maximumPositions > MAX_TOTAL_POSITIONS || settings.longSlots + settings.shortSlots !== settings.maximumPositions) throw new Error("Positielimieten zijn ongeldig: maximaal 100 totaal en LONG + SHORT moet exact gelijk zijn aan totaal.");
      // Minimum leverage is only a candidate floor. Automatic Top-N still resolves every
      // symbol at its actual maximum valid leverage unless Maximum leverage supplies an
      // optional cap, and skips symbols whose Aster maximum cannot satisfy the minimum.
      // Null Maximum leverage deliberately preserves the established pair-maximum behavior.
      if (settings.maximumLeverage !== null && settings.maximumLeverage < settings.minimumLeverage) throw new Error("Maximum leverage moet gelijk aan of hoger zijn dan Minimum leverage.");
      if (settings.stopLossEnabled && (settings.stopLossLong <= 0 || settings.stopLossShort <= 0)) throw new Error("Stoploss LONG en SHORT moeten groter dan 0 zijn wanneer Stoploss aan staat.");
      if (settings.entrySizingMode === "notional") {
        if (settings.longSlots > 0 && settings.entryNotionalLongUsd <= 0) throw new Error("Positie LONG moet groter dan 0 USDT zijn.");
        if (settings.shortSlots > 0 && settings.entryNotionalShortUsd <= 0) throw new Error("Positie SHORT moet groter dan 0 USDT zijn.");
      } else {
        if (settings.longSlots > 0 && settings.entryMarginLongUsd <= 0) throw new Error("Instapmargin LONG moet groter dan 0 USDT zijn.");
        if (settings.shortSlots > 0 && settings.entryMarginShortUsd <= 0) throw new Error("Instapmargin SHORT moet groter dan 0 USDT zijn.");
      }
      if (settings.longDcaDistance <= 0 || settings.shortDcaDistance <= 0 || settings.longDcaDistance > .5 || settings.shortDcaDistance > .5) throw new Error("DCA-afstand moet tussen 0,01% en 50% liggen.");
      if (settings.longDcaMarginUsd <= 0 || settings.shortDcaMarginUsd <= 0) throw new Error("DCA-bedrag LONG/SHORT moet positief zijn.");
      if (settings.maxDcaLong > MAX_DCA || settings.maxDcaShort > MAX_DCA) throw new Error(`Max DCA mag maximaal ${MAX_DCA} zijn.`);
      if (v.tpMode === "PER_TRADE" && (settings.longTakeProfitValue <= 0 || settings.shortTakeProfitValue <= 0)) throw new Error("Take Profit LONG/SHORT moet positief zijn.");
      if (v.tpMode === "PORTFOLIO") {
        if (settings.portfolioTpValue <= 0) throw new Error("Portfolio TP moet groter dan 0 zijn.");
        if (settings.portfolioTpInputMode === "PERCENT" && settings.portfolioTpValue > 10000) throw new Error("Portfolio TP percentage mag maximaal 10.000% zijn.");
        if (settings.portfolioTpBaseMode === "CUSTOM" && settings.portfolioTpCustomBaseEquity <= 0) throw new Error("Vul bij Aangepast een geldige basiswaarde groter dan 0 in.");
      }
      if (v.smartRescueEnabled) {
        if (!(settings.smartRescueRangePercent > 0 && settings.smartRescueRangePercent < 100)) throw new Error("Smart Rescue bereik moet groter dan 0% en kleiner dan 100% zijn.");
        if (!(settings.smartRescueDcaCount >= 1 && settings.smartRescueDcaCount <= MAX_DCA)) throw new Error(`Smart Rescue aantal DCA's moet tussen 1 en ${MAX_DCA} liggen.`);
        if (!(settings.smartRescueOrderGrowthMultiplier >= 1)) throw new Error("Smart Rescue ordergroei moet minimaal 1,00× zijn.");
        if (!(settings.smartRescueTrailingRecoveryPercent >= 0 && settings.smartRescueTrailingRecoveryPercent < 100)) throw new Error("Smart Rescue herstel moet tussen 0% en 100% liggen.");
      }
      if (v.manualEnabled && !v.manualSymbols.length) throw new Error("Selecteer minimaal één Aster USDT perpetual of zet handmatige selectie uit.");
      if (kind === "start" && v.manualEnabled) { const blocked = v.manualSymbols.map((row) => tierPreviews[row.symbol]).filter((row) => row?.entryOrderValid === false); if (blocked.length) throw new Error(`${blocked[0].symbol}: instapmargin voldoet niet aan de actuele Aster minimumorder.`); }
      const outgoingSettings = kind === "stop" ? settings : await withLatestProfitLockSettings(settings);
      const route = kind === "save" ? "settings" : kind; const method = kind === "save" ? "PUT" : "POST"; const body = kind === "start" ? { confirm: true, settings: outgoingSettings } : kind === "stop" ? { confirm: true } : { settings: outgoingSettings };
      const result = await authenticatedRequest(`/api/exchanges/aster/strategy2/${route}`, { method, body: JSON.stringify(body) }) as Record<string, unknown>;
      const confirmed = result.strategy2 && typeof result.strategy2 === "object" ? result.strategy2 as Record<string, unknown> : null; if (confirmed) { setConfirmedState(confirmed); onConfirmed(confirmed); }
      if (kind === "save") {
        const savedSettings = confirmed?.settings && typeof confirmed.settings === "object" ? confirmed.settings as Record<string, unknown> : null;
        if (!savedSettings) throw new Error("Server bevestigde de opgeslagen Botinstellingen niet.");
        const savedMax = savedSettings.maximumLeverage === null || savedSettings.maximumLeverage === undefined ? null : Number(savedSettings.maximumLeverage);
        if (savedMax !== settings.maximumLeverage) throw new Error("Maximum leverage is niet server-side bevestigd; instellingen blijven als niet opgeslagen gemarkeerd.");
        const savedSizing = String(savedSettings.entrySizingMode || "margin").toLowerCase();
        if (savedSizing !== settings.entrySizingMode) throw new Error("Positieomvang-modus is niet server-side bevestigd; instellingen blijven als niet opgeslagen gemarkeerd.");
        setV((current) => ({ ...current, maxLeverage: savedMax === null ? "" : String(savedMax), fixedPositionSize: savedSizing === "notional" }));
        setDirty(false); setMessage("Instellingen server-side opgeslagen en bevestigd. Actieve posities, fills, avg entry, DCA-counts en Portfolio TP-cycle zijn intact gebleven.");
      }
      else if (kind === "simulate") setMessage("Configuratie veilig gesimuleerd: 0 orders verzonden.");
      else if (kind === "stop") setMessage("Bot-stop door server verwerkt.");
      else { const firstTick = result.firstTick && typeof result.firstTick === "object" ? result.firstTick as Record<string, unknown> : null; const reason = String(firstTick?.reason || confirmed?.lastReason || "").trim(); setMessage(result.started === true && confirmed?.enabled === true ? `Bot server-side gestart${reason ? ` · ${reason}` : ""}.` : `Start niet bevestigd${reason ? `: ${reason}` : "."}`); }
      await Promise.resolve(onChanged());
    } catch (error) { setMessage(error instanceof Error ? error.message : "Actie mislukt"); }
    finally { setBusy(false); }
  }
  async function resetPortfolioCycle() {
    if (busy) return;
    setBusy(true); setMessage("");
    try {
      const result = await authenticatedRequest("/api/exchanges/aster/strategy2/portfolio-cycle/reset", { method: "POST", body: JSON.stringify({ confirm: true }) }) as Record<string, unknown>;
      if (result.reset !== true || Number(result.ordersSent ?? -1) !== 0) throw new Error("Reset cycle is niet veilig server-side bevestigd.");
      const confirmed = result.strategy2 && typeof result.strategy2 === "object" ? result.strategy2 as Record<string, unknown> : null;
      if (confirmed) { setConfirmedState(confirmed); onConfirmed(confirmed); }
      setV((current) => ({ ...current, portfolioTpBaseMode: "CYCLE_START" }));
      setMessage(`Cycle start gereset naar huidige equity ${Number(result.cycleStartEquity || 0).toLocaleString("nl-NL", { style: "currency", currency: "USD" })}. 0 orders verzonden.`);
      await Promise.resolve(onChanged());
    } catch (error) { setMessage(error instanceof Error ? error.message : "Reset cycle mislukt"); }
    finally { setBusy(false); }
  }

  async function checkReadiness(startWhenReady = false) {
    setBusy(true); setMessage("");
    try { const result = await authenticatedRequest("/api/exchanges/aster/strategy2/readiness") as Record<string, unknown>; setReadiness(result); if (startWhenReady && Boolean(result.liveReady)) { setBusy(false); await action("start"); return; } setMessage(Boolean(result.liveReady) ? "Live-gereedheid server-side bevestigd." : "Readiness gecontroleerd; live-start is nog niet vrijgegeven."); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Readiness mislukt"); }
    finally { setBusy(false); }
  }

  const enabled = status.enabled === true; const liveReady = status.liveReady === true || (!status.pending && readiness?.liveReady === true);
  // Position counts come from the current persisted bot state. A scan report can
  // belong to the previous settings version for up to one scheduler interval, so
  // never let stale remainingLong/remainingShort override the slots shown above.
  const activeLong = Number(state.longLegs ?? rawReport.activeLong ?? 0); const activeShort = Number(state.shortLegs ?? rawReport.activeShort ?? 0);
  const remainingLong = Math.max(0, n(v.longSlots) - activeLong); const remainingShort = Math.max(0, n(v.shortSlots) - activeShort);
  const displayRemainingLong = v.smartRescueEnabled ? Math.max(0, n(v.positions) - activeLong) : remainingLong;
  const displayRemainingShort = v.smartRescueEnabled ? 0 : remainingShort;
  const reportCurrent = Number(rawReport.configVersion ?? 0) === Number(state.configVersion ?? persisted.version ?? 0);
  const candidateCount = reportCurrent ? Number(rawReport.candidateCount ?? 0) : 0; const scannedCandidateCount = reportCurrent ? Number(rawReport.scannedCandidateCount ?? 0) : 0;
  const snapshotAccount = (snapshot?.account && typeof snapshot.account === "object" ? snapshot.account : {}) as Record<string, unknown>;
  const portfolioEquity = finiteOr(snapshot?.equity ?? snapshot?.portfolioValue ?? snapshotAccount.totalMarginBalance ?? snapshotAccount.marginBalance ?? snapshotAccount.totalWalletBalance, 0);
  const availableBalance = finiteOr(snapshot?.availableBalance ?? snapshotAccount.availableBalance ?? snapshotAccount.availableMargin, 0);
  const cycleStart = finiteOr(cycle.cycleStartEquity, 0);
  const currentEquity = finiteOr(cycle.currentEquity, portfolioEquity);
  const serverBase = finiteOr(cycle.baseEquity, 0);
  const previewBase = v.portfolioTpBaseMode === "CURRENT_VALUE" ? currentEquity : v.portfolioTpBaseMode === "CUSTOM" ? n(v.portfolioTpCustomBase) : cycleStart;
  const effectiveBase = dirty ? previewBase : serverBase || previewBase;
  const serverInputMode = portfolioTpInputModeFrom(cycle.takeProfitInputMode);
  const serverTpValue = finiteOr(cycle.takeProfitValue, 0);
  const effectiveInputMode = dirty ? v.portfolioTpInputMode : cycle.takeProfitInputMode ? serverInputMode : v.portfolioTpInputMode;
  const effectiveTpValue = dirty ? n(v.portfolioTp) : serverTpValue > 0 ? serverTpValue : n(v.portfolioTp);
  const target = dirty ? portfolioTarget(previewBase, v.portfolioTpInputMode, n(v.portfolioTp)) : finiteOr(cycle.targetEquity, portfolioTarget(effectiveBase, effectiveInputMode, effectiveTpValue));
  const portfolioWarning = v.tpMode === "PORTFOLIO" && target > 0 && currentEquity >= target;
  const effectiveBaseMode = dirty ? v.portfolioTpBaseMode : cycle.baseMode ? portfolioTpBaseModeFrom(cycle.baseMode) : v.portfolioTpBaseMode;
  const tpBadge = effectiveInputMode === "USD" ? `+${money2(effectiveTpValue)}` : `+${effectiveTpValue.toLocaleString("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
  const firstSelectedLeverage = v.manualEnabled && v.manualSymbols.length ? tierPreviews[v.manualSymbols[0]?.symbol]?.entryPlan?.leverage || tierPreviews[v.manualSymbols[0]?.symbol]?.currentLeverage : 0;
  const smartPreviewLeverage = Math.max(1, Number(firstSelectedLeverage || n(v.minLeverage) || 1));
  const smartStartMargin = v.fixedPositionSize ? Math.max(.00000001, n(v.entryNotionalLong) / smartPreviewLeverage) : Math.max(.00000001, n(v.entryMarginLong));
  const smartPreview = useMemo(() => buildSmartPreview(smartStartMargin, smartPreviewLeverage, Math.max(.000001, n(v.smartRescueRange)), clampInt(n(v.smartRescueCount), 1, MAX_DCA), Math.max(1, n(v.smartRescueGrowth))), [smartStartMargin, v.smartRescueRange, v.smartRescueCount, v.smartRescueGrowth, smartPreviewLeverage]);
  const smartPortfolioImpact = portfolioEquity > 0 ? smartPreview.maxMargin / portfolioEquity * 100 : 0;
  const smartStressSeats = Math.max(1, clampInt(n(v.positions), 1, MAX_TOTAL_POSITIONS));
  const smartAllSeatsMargin = Math.min(MAX_PREVIEW_MONEY, smartPreview.maxMargin * smartStressSeats);
  const smartStressImpact = portfolioEquity > 0 ? smartAllSeatsMargin / portfolioEquity * 100 : 0;
  const smartRiskLevel = smartPortfolioImpact > 100 || smartStressImpact > 100 ? "danger" : smartPortfolioImpact > 75 || smartStressImpact > 75 ? "high" : smartPortfolioImpact > 50 || smartStressImpact > 50 ? "warn" : "ok";
  const managedPositions = (state.multiBbPositions && typeof state.multiBbPositions === "object" ? state.multiBbPositions : {}) as Record<string, unknown>;
  const exchangePositions = Array.isArray(snapshot?.positions) ? snapshot.positions as Array<Record<string, unknown>> : [];
  const smartLiveRows = Object.entries(managedPositions).flatMap(([key, value]) => {
    if (!value || typeof value !== "object") return [];
    const managed = value as Record<string, unknown>; const smart = managed.smartRescue && typeof managed.smartRescue === "object" ? managed.smartRescue as Record<string, unknown> : null;
    const [symbol, side] = key.split("|"); if (!smart || side !== "LONG") return [];
    const live = exchangePositions.find((row) => String(row.symbol || "").toUpperCase() === symbol && String(row.positionSide || row.side || "").toUpperCase() === "LONG");
    const current = finiteOr(live?.markPrice ?? live?.price ?? managed.lastKnownEntry ?? smart.localLow, 0);
    const averageEntry = finiteOr(live?.entryPrice ?? managed.lastKnownEntry ?? smart.initialEntryPrice, 0);
    const qty = Math.abs(finiteOr(live?.positionAmt ?? live?.quantity ?? managed.lastKnownQty, 0));
    const levels = Array.isArray(smart.levels) ? smart.levels.filter((row): row is Record<string, unknown> => Boolean(row && typeof row === "object")) : [];
    const armedIndex = Math.max(0, Math.round(finiteOr(smart.armedIndex, 0)));
    const next = levels.find((row) => String(row.status || "") === "ARMED") || levels.find((row) => String(row.status || "") === "PENDING");
    const breakEven = averageEntry; const recovery = current > 0 && breakEven > 0 ? Math.max(0, (breakEven / current - 1) * 100) : 0;
    return [{ symbol, current, averageEntry, breakEven, recovery, qty, notional: qty * current, pnl: qty * (current - averageEntry),
      filled: Math.round(finiteOr(smart.filledCount, levels.filter((row) => row.status === "FILLED").length)), skipped: Math.round(finiteOr(smart.skippedCount, levels.filter((row) => row.status === "SKIPPED").length)),
      total: Math.round(finiteOr(smart.dcaCountConfigured, levels.length)), armedIndex, nextTrigger: finiteOr(next?.triggerPrice, 0),
      localLow: finiteOr(smart.localLow, 0), recoveryTrigger: finiteOr(smart.recoveryTriggerPrice, 0), margin: finiteOr(smart.cumulativeActualMarginUsd, 0) }];
  });
  const longCapacity = Math.max(0, n(v.longSlots)); const shortCapacity = Math.max(0, n(v.shortSlots)); const totalCapacity = Math.max(0, longCapacity + shortCapacity);
  const totalActive = activeLong + activeShort;
  const longFill = longCapacity > 0 ? Math.min(100, activeLong / longCapacity * 100) : 0;
  const shortFill = shortCapacity > 0 ? Math.min(100, activeShort / shortCapacity * 100) : 0;
  const totalFill = totalCapacity > 0 ? Math.min(100, totalActive / totalCapacity * 100) : 0;
  async function toggleLive() { if (status.pending || busy) return; if (dirty) { setMessage("Sla eerst de gewijzigde instellingen op; daarna kun je de bot direct aan- of uitzetten."); return; } if (enabled) return action("stop"); if (liveReady) return action("start"); return checkReadiness(true); }

  return <article id="strategy-2-maker" className="strategy-card strategy-two-card botsettings-ref" data-reference={BOT_SETTINGS_REFERENCE}>
    <div className="strategy-title-row"><div><span className="kicker">ASTER BOT</span><h2>Botinstellingen</h2></div><span className={`strategy-state ${enabled ? "on" : ""}`}>{status.pending ? "BEZIG" : enabled ? "AAN" : "UIT"}</span></div>

    <section className="slot-overview" aria-label="Slot-overzicht">
      <header><span className="slot-icon">◇</span><div><b>Slot-overzicht</b><small>Bezetting van beschikbare botslots</small></div><span className="slot-cross">⇄ <b>CROSS</b></span><span className="slot-candidates">♙ <b>{candidateCount}</b> kandidaten</span></header>
      <div className="slot-row long"><strong>LONG</strong><i><u style={{ width: `${longFill}%` }} /></i><b>{activeLong} / {longCapacity}</b><em>{displayRemainingLong} vrij</em></div>
      <div className="slot-row short"><strong>SHORT</strong><i><u style={{ width: `${shortFill}%` }} /></i><b>{activeShort} / {shortCapacity}</b><em>{displayRemainingShort} vrij</em></div>
      <div className="slot-row total"><strong>Totaal</strong><i><u style={{ width: `${totalFill}%` }} /></i><b>{totalActive} / {totalCapacity}</b><em>{Math.max(0, totalCapacity - totalActive)} vrij</em></div>
      {dirty && <small className="slot-dirty">Niet opgeslagen</small>}
    </section>

    <section className="live-settings-card">
      <div className={`strategy-power-control live-power ${enabled ? "enabled" : "ready"}`}><span><b><i className="live-dot" />Aster live bot</b><small>{dirty ? "eerst wijzigingen opslaan" : enabled ? "server bevestigt actief" : "uit"}</small></span><button type="button" role="switch" aria-checked={enabled} disabled={busy || status.pending} onClick={toggleLive}><i />{busy ? "Bezig…" : enabled ? "Uitschakelen" : "Inschakelen"}</button></div>
      <div className="live-config-grid">
        <Field label="Botnaam" value={v.name} set={(value) => change({ ...v, name: value })} text />
        <Field label="Top-N volume" value={v.universe} set={(value) => change({ ...v, universe: value })} />
        <Field label="Totaal posities" value={totalDraft ?? v.positions} set={setTotalDraft} onBlur={commitTotal} />
        <Field label="LONG slots" value={longDraft ?? v.longSlots} set={setLongDraft} onBlur={commitLong} />
        <Field label="SHORT slots" value={shortDraft ?? v.shortSlots} set={setShortDraft} onBlur={commitShort} />
        <Field label="Minimum leverage" value={v.minLeverage} set={(value) => change({ ...v, minLeverage: value })} />
        <Field label="Maximum leverage" value={v.maxLeverage} set={(value) => change({ ...v, maxLeverage: value })} />
      </div>
      <small className="leverage-caption">{v.maxLeverage.trim() ? `Leverage wordt begrensd op ${Math.max(1, Math.round(n(v.maxLeverage)))}x.` : "Maximum leverage leeg = bestaande pair-maximumlogica."}</small>
    </section>

    <div className={"strategy-power-control entry-sizing-control " + (v.fixedPositionSize ? "enabled" : "ready")}>
      <span className="pair-icon">◎</span><span><b>Vaste positieomvang</b><small>Aan: instapbedrag = totale positie in USDT · margin = positie ÷ leverage. Uit: instapbedrag = margin.</small></span>
      <button type="button" role="switch" aria-checked={v.fixedPositionSize} onClick={() => change({ ...v, fixedPositionSize: !v.fixedPositionSize })}><i />{v.fixedPositionSize ? "Aan" : "Uit"}</button>
    </div>

    <div className="maker-input compact-settings-grid">
      <div className={`strategy-power-control short-pair-control ${v.shortRequiresLongEnabled ? "enabled" : "ready"}`}><span className="pair-icon">↗</span><span><b>SHORT alleen met LONG</b><small>LONG mag altijd zelfstandig openen · ontbrekende LONG krijgt scanner-prioriteit.</small></span><button type="button" role="switch" aria-checked={v.shortRequiresLongEnabled} onClick={() => change({ ...v, shortRequiresLongEnabled: !v.shortRequiresLongEnabled })}><i />{v.shortRequiresLongEnabled ? "Aan" : "Uit"}</button></div>

      <section className="side-settings-block">
        <div className="side-settings-head"><div><small>GEÏNTEGREERD</small><b>LONG / SHORT · DCA & Take Profit</b></div></div>
        <div className="tp-tabs" aria-label="Take Profit modus">{(["PER_TRADE", "PORTFOLIO", "OFF"] as TpMode[]).map((mode) => <button key={mode} type="button" aria-pressed={v.tpMode === mode} className={v.tpMode === mode ? "active" : ""} onClick={() => change({ ...v, tpMode: mode })}>{mode === "PER_TRADE" ? "Per trade" : mode === "PORTFOLIO" ? "Portfolio" : "Uit"}</button>)}</div>
        {v.tpMode === "PORTFOLIO" && <section className="portfolio-tp-panel" data-visual-reference={PORTFOLIO_TP_REFERENCE} aria-label="Portfolio Take Profit">
          <header className="portfolio-tp-head"><span className="portfolio-tp-icon">◎</span><span><b>Portfolio Take Profit</b><small>Sluit alle posities wanneer de portfoliowaarde je doel bereikt.</small></span><i title="Portfolio TP sluit alle posities veilig en start daarna een nieuwe cycle vanaf de werkelijke sluitwaarde.">i</i></header>
          <div className="portfolio-tp-controls">
            <div className="portfolio-choice"><small>TP invoermodus</small><div className="segmented two"><button type="button" aria-pressed={v.portfolioTpInputMode === "PERCENT"} className={v.portfolioTpInputMode === "PERCENT" ? "active" : ""} onClick={() => change({ ...v, portfolioTpInputMode: "PERCENT" })}>%</button><button type="button" aria-pressed={v.portfolioTpInputMode === "USD"} className={v.portfolioTpInputMode === "USD" ? "active" : ""} onClick={() => change({ ...v, portfolioTpInputMode: "USD" })}>$</button></div></div>
            <div className="portfolio-choice base-choice"><small>Bereken vanaf</small><div className="segmented three">{([
              ["CYCLE_START", "Cycle start"], ["CURRENT_VALUE", "Huidige waarde"], ["CUSTOM", "Aangepast"],
            ] as [PortfolioTpBaseMode, string][]).map(([mode, label]) => <button key={mode} type="button" aria-pressed={v.portfolioTpBaseMode === mode} className={v.portfolioTpBaseMode === mode ? "active" : ""} onClick={() => change({ ...v, portfolioTpBaseMode: mode })}>{label}</button>)}</div></div>
          </div>
          {v.portfolioTpBaseMode === "CYCLE_START" && <div className="cycle-reset-row"><button type="button" disabled={busy} onClick={() => void resetPortfolioCycle()}>↻ <b>Reset cycle</b></button><span>Reset zet cycle start gelijk aan huidige equity.</span></div>}
          <div className="portfolio-input-grid">
            <Field label={v.portfolioTpInputMode === "USD" ? "Portfolio TP ($)" : "Portfolio TP (%)"} value={v.portfolioTp} set={(value) => change({ ...v, portfolioTp: value })} suffix={v.portfolioTpInputMode === "USD" ? "$" : "%"} />
            {v.portfolioTpBaseMode === "CUSTOM"
              ? <Field label="Basiswaarde" value={v.portfolioTpCustomBase} set={(value) => change({ ...v, portfolioTpCustomBase: value })} suffix="$" />
              : <label className="basis-readonly"><span>Basiswaarde <i title="Deze waarde wordt door de cycle vastgezet.">i</i></span><strong>${money2(dirty ? previewBase : effectiveBase)}</strong><em>✎</em></label>}
          </div>
          <div className="portfolio-target-flow">
            <div className="equity-card"><span className="value-icon">◉</span><span><small>Huidige portfoliowaarde</small><em>Equity</em><b>${money2(currentEquity)}</b></span></div>
            <strong className="target-arrow">→</strong>
            <div className="target-card"><span className="value-icon">◉</span><span><small>Doelwaarde</small><b>${money2(target)}</b></span><em className="target-badge">{tpBadge}</em></div>
          </div>
          <p className="portfolio-target-note">Doel wordt berekend vanaf de gekozen basiswaarde.</p>
          <p className="portfolio-cycle-note">ⓘ Na sluiting wordt de werkelijke sluitwaarde de nieuwe cycle start voor de volgende cyclus.</p>
          <div className="portfolio-status-strip">
            <span><i>⌁</i><small>Cycle start</small><b>${money2(cycleStart)}</b></span>
            <span><i>◉</i><small>Equity</small><b>${money2(currentEquity)}</b></span>
            <span><i>▱</i><small>Basis</small><b>${money2(effectiveBase)}</b></span>
            <span><i>◎</i><small>Target</small><b>${money2(target)}</b></span>
          </div>
          <small className="portfolio-base-state">Actieve basis: {effectiveBaseMode === "CURRENT_VALUE" ? "Huidige waarde (vastgezet)" : effectiveBaseMode === "CUSTOM" ? "Aangepast" : "Cycle start"}</small>
          {portfolioWarning && <em className="portfolio-warning">Target ligt op of onder de huidige equity; na opslaan kan Portfolio TP direct veilig uitvoeren.</em>}
        </section>}
        {v.tpMode === "OFF" && <p className="tp-off-note">Automatische TP uit. DCA en overige strategie blijven actief.</p>}
        <div className="side-columns">
          <section className="side-card long"><b>LONG</b><Field label={v.fixedPositionSize ? "Instap LONG · positie" : "Instap LONG · margin"} value={v.fixedPositionSize ? v.entryNotionalLong : v.entryMarginLong} set={(value) => v.fixedPositionSize ? change({ ...v, entryNotionalLong: value }) : change({ ...v, entryMarginLong: value })} suffix="USDT" /><Field label="DCA-afstand LONG" value={v.longDcaDistance} set={(value) => change({ ...v, longDcaDistance: value })} suffix="%" disabled={v.smartRescueEnabled} /><Field label="DCA-bedrag LONG" value={v.longDcaAmount} set={(value) => change({ ...v, longDcaAmount: value })} suffix="USDT" disabled={v.smartRescueEnabled} /><Field label="Max DCA LONG" value={v.maxDcaLong} set={(value) => change({ ...v, maxDcaLong: value })} disabled={v.smartRescueEnabled} /><Field label="Take Profit LONG" value={v.longTp} set={(value) => change({ ...v, longTp: value })} suffix="%" disabled={v.tpMode !== "PER_TRADE"} /></section>
          <section className={`side-card short ${v.smartRescueEnabled ? "inactive" : ""}`}><b>SHORT {v.smartRescueEnabled ? "· bewaard, runtime uit" : ""}</b><Field label={v.fixedPositionSize ? "Instap SHORT · positie" : "Instap SHORT · margin"} value={v.fixedPositionSize ? v.entryNotionalShort : v.entryMarginShort} set={(value) => v.fixedPositionSize ? change({ ...v, entryNotionalShort: value }) : change({ ...v, entryMarginShort: value })} suffix="USDT" disabled={v.smartRescueEnabled} /><Field label="DCA-afstand SHORT" value={v.shortDcaDistance} set={(value) => change({ ...v, shortDcaDistance: value })} suffix="%" disabled={v.smartRescueEnabled} /><Field label="DCA-bedrag SHORT" value={v.shortDcaAmount} set={(value) => change({ ...v, shortDcaAmount: value })} suffix="USDT" disabled={v.smartRescueEnabled} /><Field label="Max DCA SHORT" value={v.maxDcaShort} set={(value) => change({ ...v, maxDcaShort: value })} disabled={v.smartRescueEnabled} /><Field label="Take Profit SHORT" value={v.shortTp} set={(value) => change({ ...v, shortTp: value })} suffix="%" disabled={v.smartRescueEnabled || v.tpMode !== "PER_TRADE"} /></section>
        </div>
      </section>

      <section className={`stop-loss-card ${v.stopLossEnabled ? "enabled" : ""}`} aria-label="Stoploss">
        <div className="stop-loss-head"><span className="stop-loss-icon">♢</span><span><b>Stoploss</b><small>Sluit trade automatisch bij maximaal verlies.</small></span><button type="button" className={v.stopLossEnabled ? "on" : ""} role="switch" aria-checked={v.stopLossEnabled} onClick={() => change({ ...v, stopLossEnabled: !v.stopLossEnabled })}><i />{v.stopLossEnabled ? "Aan" : "Uit"}</button><span className="stop-loss-type"><small>Type:</small><button type="button" className={v.stopLossMode === "USD" ? "active" : ""} onClick={() => change({ ...v, stopLossMode: "USD" })}>$</button><button type="button" className={v.stopLossMode === "PERCENT" ? "active" : ""} onClick={() => change({ ...v, stopLossMode: "PERCENT" })}>%</button></span></div>
        <div className="stop-loss-fields"><Field label="Stoploss LONG" value={v.stopLossLong} set={(value) => change({ ...v, stopLossLong: value })} suffix={v.stopLossMode === "USD" ? "USDT" : "%"} /><Field label="Stoploss SHORT" value={v.stopLossShort} set={(value) => change({ ...v, stopLossShort: value })} suffix={v.stopLossMode === "USD" ? "USDT" : "%"} /></div>
      </section>

      {/* Smart Rescue keeps its existing behavior; only the collapsed card is visually compact. */}
      <section className={`smart-rescue-card ${v.smartRescueEnabled ? "enabled" : ""}`}>
        <label className="smart-rescue-toggle"><span><small>NIEUW · OPTIONELE DCA-MODUS</small><b>Smart Rescue DCA</b><em>Progressieve LONG-rescues · pas kopen na herstel</em></span><input type="checkbox" checked={v.smartRescueEnabled} onChange={(event) => change({ ...v, smartRescueEnabled: event.target.checked })} /></label>
        {v.smartRescueEnabled && <div className="smart-rescue-body">
          <p className="smart-rescue-note">Vervangt alleen de normale LONG-DCA voor <b>nieuwe Smart Rescue-cycli</b>. Tijdens Smart Rescue wordt de totale positiecapaciteit LONG-only gebruikt; opgeslagen LONG/SHORT- en normale DCA-waarden blijven bewaard voor wanneer je deze modus weer uitzet. Bestaande posities blijven op hun eigen strategie. Portfolio Take Profit blijft een volledig zelfstandige bestaande instelling.</p>
          <div className="smart-rescue-fields"><Field label="Rescue bereik" value={v.smartRescueRange} set={(value) => change({ ...v, smartRescueRange: value })} suffix="%" /><Field label="Aantal DCA's" value={v.smartRescueCount} set={(value) => change({ ...v, smartRescueCount: value })} /><Field label="Ordergroei" value={v.smartRescueGrowth} set={(value) => change({ ...v, smartRescueGrowth: value })} suffix="×" /><Field label="Koop na herstel" value={v.smartRescueRecovery} set={(value) => change({ ...v, smartRescueRecovery: value })} suffix="%" /></div>
          <div className="smart-rescue-summary"><div><small>LADDER</small><b>{clampInt(n(v.smartRescueCount), 1, MAX_DCA)} DCA’s · {n(v.smartRescueRange).toFixed(2)}%</b></div><div><small>MAX INZET / MUNT</small><b>{money(smartPreview.maxMargin)}</b></div><div><small>BREAK-EVEN DIEPSTE STAP</small><b>+{smartPreview.finalRecovery.toFixed(2)}%</b></div><div><small>PREVIEW LEVERAGE</small><b>{smartPreviewLeverage}×</b></div></div>
          <div className="smart-rescue-chart" aria-label="Smart Rescue break-even visualisatie"><SmartRescueChart rows={smartPreview.rows} current={smartPreview.finalPrice} breakEven={smartPreview.finalBreakEven} recovery={smartPreview.finalRecovery} /></div>
          <div className={`smart-rescue-risk ${smartRiskLevel}`}><div className="risk-head"><span><small>KAPITAALBELASTING</small><b>{smartRiskLevel === "danger" ? "Zeer zware Rescue-ladder" : smartRiskLevel === "high" ? "Hoge kapitaalbelasting" : smartRiskLevel === "warn" ? "Agressieve configuratie" : "Binnen huidige rekenruimte"}</b></span><strong>{portfolioEquity > 0 ? `${smartPortfolioImpact.toFixed(1)}%` : "—"}</strong></div><div className="risk-bars"><label><span>Portfolio equity</span><i><u style={{ width: "100%" }} /></i><b>{portfolioEquity > 0 ? money(portfolioEquity) : "—"}</b></label><label><span>Volledige ladder / munt</span><i><u style={{ width: `${Math.min(100, smartPortfolioImpact || 0)}%` }} /></i><b>{money(smartPreview.maxMargin)}</b></label></div><div className="stress-grid"><span><small>1 munt volledig</small><b>{money(smartPreview.maxMargin)}</b></span><span><small>5 munten volledig</small><b>{money(Math.min(MAX_PREVIEW_MONEY, smartPreview.maxMargin * 5))}</b></span><span><small>{smartStressSeats} actieve stoelen volledig</small><b>{money(smartAllSeatsMargin)}</b></span><span><small>Available</small><b>{availableBalance > 0 ? money(availableBalance) : "—"}</b></span></div>{(smartPortfolioImpact > 100 || smartStressImpact > 100) && <p><b>⚠ Alleen waarschuwing — opslaan blijft mogelijk.</b> Als de volledige ladder(s) worden geraakt, vraagt deze configuratie meer kapitaal dan de huidige portfolio-equity. Onvoldoende beschikbare margin kan voorkomen dat alle rescue-orders worden uitgevoerd.</p>}{smartPreview.capped && <p><b>⚠ Extreem grote getallen.</b> De preview is voor weergave begrensd; de configuratie blijft opslaanbaar zolang de invoer technisch geldig is.</p>}</div>
          {smartLiveRows.length > 0 && <details className="smart-rescue-live" open><summary>Live Smart Rescue-posities <span>{smartLiveRows.length}</span></summary><div className="smart-live-list">{smartLiveRows.map((row) => <article key={row.symbol}><header><b>{row.symbol}</b><em>{row.armedIndex ? `ARMED · DCA ${row.armedIndex}` : `${row.filled}/${row.total} DCA gevuld`}</em></header><div className="smart-live-grid"><span><small>Huidige koers</small><b>{row.current ? row.current.toFixed(6) : "—"}</b></span><span><small>Gem. entry</small><b>{row.averageEntry ? row.averageEntry.toFixed(6) : "—"}</b></span><span><small>Break-even*</small><b>{row.breakEven ? row.breakEven.toFixed(6) : "—"}</b></span><span><small>Nog herstel</small><b>+{row.recovery.toFixed(2)}%</b></span><span><small>Ingezet / margin</small><b>{money(row.margin)}</b></span><span><small>Notional</small><b>{money(row.notional)}</b></span><span><small>Open PnL</small><b>{money(row.pnl)}</b></span><span><small>Filled / skipped</small><b>{row.filled} / {row.skipped}</b></span></div><div className="smart-live-next"><span>Volgende rescue</span><b>{row.nextTrigger ? row.nextTrigger.toFixed(6) : "Ladder klaar"}</b>{row.armedIndex > 0 && <em>Trailing low {row.localLow.toFixed(6)} · BUY-herstel {row.recoveryTrigger.toFixed(6)}</em>}</div><small>* Live break-evenkaart gebruikt weighted entry; onbekende toekomstige fees/funding zijn niet verzonnen. Backend en Aster-fills blijven source of truth.</small></article>)}</div></details>}
          <details className="smart-rescue-details"><summary>Bekijk volledige DCA-ladder <span>›</span></summary><div className="smart-rescue-table-wrap"><table><thead><tr><th>Stap</th><th>Daling</th><th>Koersindex</th><th>Nieuwe DCA</th><th>Totaal ingezet</th><th>Notional</th><th>Gem. entry</th><th>Open PnL</th><th>Break-even</th><th>Herstel</th></tr></thead><tbody><tr><td>Start</td><td>0,00%</td><td>100,0000</td><td>{money(n(v.entryMarginLong))}</td><td>{money(n(v.entryMarginLong))}</td><td>{money(n(v.entryMarginLong) * smartPreviewLeverage)}</td><td>100,0000</td><td>$0,00</td><td>100,0000</td><td>0,00%</td></tr>{smartPreview.rows.map((row) => <tr key={row.index}><td>DCA {row.index}</td><td>-{row.drop.toFixed(2)}%</td><td>{row.trigger.toFixed(4)}</td><td>{money(row.orderMargin)}</td><td>{money(row.cumulativeMargin)}</td><td>{money(row.notional)}</td><td>{row.averageEntry.toFixed(4)}</td><td>{money(row.pnl)}</td><td>{row.breakEven.toFixed(4)}</td><td>+{row.recovery.toFixed(2)}%</td></tr>)}</tbody></table></div><small className="smart-rescue-disclaimer">Preview gebruikt een koersindex van 100 en theoretische trigger-fills. Live gebruikt de backend echte Aster fills, quantities, leverage en exchange-regels. Trailing herstel kan de uiteindelijke fillprijs wijzigen.</small></details>
        </div>}
      </section>

      <label className="manual-symbol-toggle"><span><b>Zelf munten kiezen</b><small>UIT = automatische Top-N. AAN = uitsluitend jouw geselecteerde Aster USDT perpetuals.</small></span><input type="checkbox" checked={v.manualEnabled} onChange={(event) => change({ ...v, manualEnabled: event.target.checked })} /></label>
      {v.manualEnabled && <div className="manual-symbol-picker"><div className="manual-symbol-search"><input value={marketSearch} onChange={(event) => setMarketSearch(event.target.value.toUpperCase())} onFocus={() => { if (!markets.length) void loadMarkets(); }} placeholder="Zoek BTC, HYPE, BTCUSDT…" /><button type="button" disabled={marketBusy || !marketQuery || !directMarket} onClick={() => { if (directMarket) addSymbol(directMarket); }}>+ toevoegen</button></div>{marketQuery && <div className="manual-symbol-results">{marketBusy ? <small>Markten laden…</small> : marketLoadError ? <button type="button" onClick={() => void loadMarkets()}>Laden mislukt · opnieuw proberen</button> : marketMatches.length ? marketMatches.map((symbol) => <button type="button" key={symbol} onClick={() => addSymbol(symbol)}>{symbol}<i>+</i></button>) : <small>Geen actieve Aster USDT perpetual gevonden.</small>}</div>}<div className="manual-symbol-selected">{v.manualSymbols.map((row) => { const preview = tierPreviews[row.symbol]; const leverage = preview?.entryPlan?.leverage || preview?.currentLeverage; return <div key={row.symbol}><div><b>{row.symbol}</b>{leverage ? <small>{leverage}×</small> : tierBusy ? <small>…</small> : null}<span><button type="button" className={v.smartRescueEnabled || row.side === "LONG" ? "active long" : ""} onClick={() => setSymbolSide(row.symbol, "LONG")}>LONG</button><button type="button" disabled={v.smartRescueEnabled} title={v.smartRescueEnabled ? "Smart Rescue draait nieuwe cycli LONG-only; je opgeslagen SHORT-keuze blijft bewaard voor wanneer Smart Rescue uit staat." : undefined} className={!v.smartRescueEnabled && row.side === "SHORT" ? "active short" : ""} onClick={() => setSymbolSide(row.symbol, "SHORT")}>SHORT</button></span><button type="button" className="remove" onClick={() => removeSymbol(row.symbol)}>×</button></div>{preview?.entryOrderValid === false && <small className="inline-warning">Instapmargin te laag. Advies minimaal ${Number(preview.suggestedEntryMarginUsd ?? preview.minimumEntryMarginUsd ?? 0).toFixed(2)}.</small>}</div>; })}</div><p className="manual-symbol-summary">{v.smartRescueEnabled ? `${v.manualSymbols.length} geselecteerd · runtime LONG-only · opgeslagen kantkeuzes blijven bewaard` : `${v.manualSymbols.length} geselecteerd · ${v.manualSymbols.filter((row) => row.side === "LONG").length} LONG · ${v.manualSymbols.filter((row) => row.side === "SHORT").length} SHORT`}</p></div>}
    </div>

    <div className="maker-nav"><button disabled={busy || !dirty} onClick={() => action("save")}>Instellingen opslaan</button><button disabled={busy} onClick={() => action("simulate")}>Veilig simuleren</button><button disabled={busy} onClick={() => checkReadiness(false)}>Readiness controleren</button></div>
    {readiness && <p className="strategy-message">Readiness: {Boolean(state.liveReady) || Boolean(readiness.liveReady) ? "LIVE READY" : "nog niet live ready"}</p>}{message && <p className="strategy-message">{message}</p>}

    <style>{`
      #strategy-2-maker.botsettings-ref{--gold:#d6b55a;--green:#21d69a;--pink:#ff5f78;background:radial-gradient(circle at 82% 4%,rgba(18,188,124,.13),transparent 34%),linear-gradient(180deg,#07110e,#030706);border:1px solid rgba(214,181,90,.54);border-radius:17px;padding:9px;box-shadow:0 18px 48px rgba(0,0,0,.36);overflow:hidden}
      #strategy-2-maker.botsettings-ref .slot-overview{display:grid;gap:3px;margin:0 0 6px;padding:6px 7px 7px;border:1px solid rgba(214,181,90,.62);border-radius:11px;background:linear-gradient(180deg,rgba(2,18,13,.96),rgba(2,11,8,.98));box-shadow:inset 0 1px rgba(255,255,255,.02)}
      #strategy-2-maker.botsettings-ref .slot-overview header{display:grid;grid-template-columns:22px minmax(0,1fr) auto auto;align-items:center;gap:6px;padding:0 1px 3px;border-bottom:1px solid rgba(255,255,255,.045)}
      #strategy-2-maker.botsettings-ref .slot-overview header>div{display:grid;gap:0}#strategy-2-maker.botsettings-ref .slot-overview header b{font-size:9px}#strategy-2-maker.botsettings-ref .slot-overview header small{font-size:6.5px;color:#7e8d86}
      #strategy-2-maker.botsettings-ref .slot-icon{display:grid;place-items:center;width:20px;height:20px;color:#31edaa;font-size:16px}#strategy-2-maker.botsettings-ref .slot-cross,#strategy-2-maker.botsettings-ref .slot-candidates{display:flex;align-items:center;gap:4px;min-height:22px;padding:0 7px;border:1px solid rgba(214,181,90,.28);border-radius:7px;color:#a8b3ad;font-size:6.5px;white-space:nowrap}#strategy-2-maker.botsettings-ref .slot-cross{color:#d7bd69}#strategy-2-maker.botsettings-ref .slot-cross b,#strategy-2-maker.botsettings-ref .slot-candidates b{font-size:7px;color:#d8e0dc}
      #strategy-2-maker.botsettings-ref .slot-row{display:grid;grid-template-columns:48px minmax(70px,1fr) 58px 48px;align-items:center;gap:6px;min-height:18px;font-size:8px}#strategy-2-maker.botsettings-ref .slot-row strong{font-size:8.5px}#strategy-2-maker.botsettings-ref .slot-row>i{display:block;height:9px;padding:1px;border:1px solid currentColor;border-radius:999px;background:rgba(255,255,255,.025);overflow:hidden}#strategy-2-maker.botsettings-ref .slot-row>i u{display:block;height:100%;border-radius:999px;background:currentColor;box-shadow:0 0 7px currentColor;text-decoration:none}#strategy-2-maker.botsettings-ref .slot-row>b{text-align:right;color:#eaf2ee;font-size:8px}#strategy-2-maker.botsettings-ref .slot-row>em{text-align:right;font-style:normal;font-size:7.5px;font-weight:900}.slot-row.long{color:#53efaf}.slot-row.short{color:#ff6b82}.slot-row.total{color:#e4bb4d}.slot-dirty{grid-column:1/-1;color:#f0bd55!important;text-align:right}
      #strategy-2-maker.botsettings-ref .live-settings-card{display:grid;gap:5px;margin-bottom:6px;padding:6px;border:1px solid rgba(214,181,90,.50);border-radius:11px;background:linear-gradient(180deg,rgba(5,24,17,.96),rgba(2,11,8,.97))}
      #strategy-2-maker.botsettings-ref .live-power{margin:0!important;padding:0 2px 3px!important;min-height:29px!important;border:0!important;border-radius:0!important;background:transparent!important}#strategy-2-maker.botsettings-ref .live-power>span b{display:flex;align-items:center;gap:5px;font-size:10px}#strategy-2-maker.botsettings-ref .live-dot{width:9px;height:9px;border-radius:50%;background:#49e47f;box-shadow:0 0 8px rgba(73,228,127,.55)}#strategy-2-maker.botsettings-ref .live-power button{min-width:110px!important}
      #strategy-2-maker.botsettings-ref .live-config-grid{display:grid;grid-template-columns:2fr 1fr .9fr .75fr .75fr .95fr .95fr;gap:3px;align-items:end}#strategy-2-maker.botsettings-ref .live-config-grid label{min-width:0;margin:0;gap:2px;font-size:6.5px;color:#b7c3bd}#strategy-2-maker.botsettings-ref .live-config-grid .field-wrap{border-radius:6px!important}#strategy-2-maker.botsettings-ref .live-config-grid input{height:28px!important;min-width:0!important;padding:0 6px!important;border:0!important;background:rgba(255,255,255,.035)!important;font-size:9px!important}#strategy-2-maker.botsettings-ref .leverage-caption{justify-self:end;margin-top:-2px;color:#73827b;font-size:6px}
      #strategy-2-maker.botsettings-ref .short-pair-control{grid-column:1/-1;display:grid!important;grid-template-columns:26px minmax(0,1fr) auto;align-items:center!important;gap:7px!important;margin:0!important;padding:6px 8px!important;min-height:43px!important}#strategy-2-maker.botsettings-ref .short-pair-control .pair-icon{display:grid;place-items:center;width:24px;height:24px;color:#38eca8;font-size:18px}#strategy-2-maker.botsettings-ref .short-pair-control>span:nth-child(2){display:grid;gap:1px}#strategy-2-maker.botsettings-ref .short-pair-control button{min-width:78px}
      #strategy-2-maker.botsettings-ref .stop-loss-card{grid-column:1/-1;display:grid;gap:5px;padding:6px 7px;border:1px solid rgba(214,181,90,.38);border-radius:11px;background:linear-gradient(180deg,rgba(3,20,14,.97),rgba(2,10,8,.98))}#strategy-2-maker.botsettings-ref .stop-loss-card.enabled{border-color:rgba(33,214,154,.52)}
      #strategy-2-maker.botsettings-ref .stop-loss-head{display:grid;grid-template-columns:26px minmax(0,1fr) auto auto;align-items:center;gap:6px}#strategy-2-maker.botsettings-ref .stop-loss-icon{display:grid;place-items:center;width:23px;height:23px;border:1px solid rgba(47,237,169,.46);border-radius:8px;color:#4ef0b0;font-size:15px}#strategy-2-maker.botsettings-ref .stop-loss-head>span:nth-child(2){display:grid;gap:0}#strategy-2-maker.botsettings-ref .stop-loss-head b{font-size:10px}#strategy-2-maker.botsettings-ref .stop-loss-head small{font-size:6.5px;color:#87978f}
      #strategy-2-maker.botsettings-ref .stop-loss-head>button{display:flex;align-items:center;gap:5px;min-width:65px;height:27px;padding:0 7px;border:1px solid rgba(93,116,105,.45);border-radius:999px;background:#111c18;color:#8c9a93;font-size:7px;font-weight:900}#strategy-2-maker.botsettings-ref .stop-loss-head>button i{width:15px;height:15px;border-radius:50%;background:#73817b}#strategy-2-maker.botsettings-ref .stop-loss-head>button.on{border-color:#22df9c;background:linear-gradient(90deg,#0b704e,#14c987);color:#fff}#strategy-2-maker.botsettings-ref .stop-loss-head>button.on i{background:#fff}
      #strategy-2-maker.botsettings-ref .stop-loss-type{display:flex!important;align-items:center;gap:3px}#strategy-2-maker.botsettings-ref .stop-loss-type small{margin-right:2px}#strategy-2-maker.botsettings-ref .stop-loss-type button{width:27px;height:24px;border:1px solid rgba(72,110,93,.48);border-radius:6px;background:#0a1511;color:#96a49d;font-size:8px;font-weight:900}#strategy-2-maker.botsettings-ref .stop-loss-type button.active{border-color:#29e6a3;background:rgba(32,201,138,.35);color:#dcfff1}
      #strategy-2-maker.botsettings-ref .stop-loss-fields{display:grid;grid-template-columns:1fr 1fr;gap:5px}#strategy-2-maker.botsettings-ref .stop-loss-fields label{margin:0;gap:2px;font-size:7px}#strategy-2-maker.botsettings-ref .stop-loss-fields input{height:27px!important;font-size:9px!important}
      #strategy-2-maker.botsettings-ref .strategy-title-row{margin-bottom:5px;align-items:center} #strategy-2-maker.botsettings-ref .strategy-title-row h2{margin:1px 0 0;font-size:21px;line-height:1} #strategy-2-maker.botsettings-ref .kicker{color:var(--gold);font-size:9px;letter-spacing:.16em}
      #strategy-2-maker.botsettings-ref .strategy-facts{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px;margin:0 0 6px} #strategy-2-maker.botsettings-ref .strategy-facts span{padding:4px 3px;border:1px solid rgba(214,181,90,.22);border-radius:8px;background:rgba(255,255,255,.02);font-size:8.5px;text-align:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      #strategy-2-maker.botsettings-ref .compact-scan{display:grid;grid-template-columns:auto 1fr auto 1fr;gap:3px 6px;padding:5px 7px;margin:0 0 6px;border:1px solid rgba(33,214,154,.18);border-radius:10px;background:rgba(3,17,13,.82);font-size:9px;align-items:center} #strategy-2-maker.botsettings-ref .compact-scan small,#strategy-2-maker.botsettings-ref .compact-scan em{grid-column:1/-1;font-size:8px;opacity:.72}
      #strategy-2-maker.botsettings-ref .strategy-power-control{padding:6px 8px;min-height:43px;margin-bottom:6px;border:1px solid rgba(214,181,90,.25);border-radius:11px;background:rgba(7,25,19,.94)} #strategy-2-maker.botsettings-ref .strategy-power-control b{font-size:11px} #strategy-2-maker.botsettings-ref .strategy-power-control small{font-size:8px} #strategy-2-maker.botsettings-ref .strategy-power-control button{min-height:31px;padding:0 9px;border-radius:9px;font-size:9px}
      #strategy-2-maker.botsettings-ref .compact-settings-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:5px} #strategy-2-maker.botsettings-ref .compact-settings-grid>label,#strategy-2-maker.botsettings-ref .position-settings-grid label,#strategy-2-maker.botsettings-ref .side-card label,#strategy-2-maker.botsettings-ref .portfolio-tp-row label{margin:0;gap:2px;font-size:9px}
      #strategy-2-maker.botsettings-ref .compact-settings-grid input{height:33px;min-width:0;padding:0 8px;border-radius:8px;border:1px solid rgba(214,181,90,.27);background:rgba(0,0,0,.28);font-size:12px} #strategy-2-maker.botsettings-ref .compact-settings-grid input:focus{border-color:rgba(33,214,154,.74);box-shadow:0 0 0 2px rgba(33,214,154,.09)}
      #strategy-2-maker.botsettings-ref .position-settings-grid{grid-column:1/-1;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px}
      #strategy-2-maker.botsettings-ref .side-settings-block{grid-column:1/-1;display:grid;gap:6px;padding:7px;border:1px solid rgba(214,181,90,.32);border-radius:12px;background:linear-gradient(180deg,rgba(5,22,16,.96),rgba(2,10,8,.96))}
      #strategy-2-maker.botsettings-ref .side-settings-head{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:end;gap:7px} #strategy-2-maker.botsettings-ref .side-settings-head>div:first-child{display:grid;gap:1px} #strategy-2-maker.botsettings-ref .side-settings-head small{font-size:7px;letter-spacing:.13em;color:var(--gold)} #strategy-2-maker.botsettings-ref .side-settings-head b{font-size:11px}
      #strategy-2-maker.botsettings-ref .tp-tabs{display:grid;grid-template-columns:repeat(3,1fr);gap:3px} #strategy-2-maker.botsettings-ref .tp-tabs button{min-height:28px;padding:0 6px;border-radius:8px;border:1px solid rgba(214,181,90,.20);background:#08100d;color:#9aa69f;font-size:8px;font-weight:800} #strategy-2-maker.botsettings-ref .tp-tabs button.active{color:#8ff4c6;border-color:rgba(33,214,154,.64);background:rgba(33,214,154,.11)}
      #strategy-2-maker.botsettings-ref .side-columns{display:grid;grid-template-columns:1fr 1fr;gap:5px} #strategy-2-maker.botsettings-ref .side-card{display:grid;gap:4px;padding:6px;border-radius:10px;background:rgba(255,255,255,.018)} #strategy-2-maker.botsettings-ref .side-card.long{border:1px solid rgba(33,214,154,.33)} #strategy-2-maker.botsettings-ref .side-card.short{border:1px solid rgba(255,120,146,.34)} #strategy-2-maker.botsettings-ref .side-card>b{font-size:10px} #strategy-2-maker.botsettings-ref .side-card.long>b{color:#67edb5} #strategy-2-maker.botsettings-ref .side-card.short>b{color:#ff90a4} #strategy-2-maker.botsettings-ref .side-card.short.inactive{opacity:.58} #strategy-2-maker.botsettings-ref .side-card label span.field-wrap{border-color:inherit}
      #strategy-2-maker.botsettings-ref .portfolio-tp-row{display:grid;grid-template-columns:1.2fr repeat(3,.8fr);gap:5px;align-items:end;padding:5px;border-radius:9px;background:rgba(62,112,161,.08);border:1px solid rgba(95,151,207,.18)} #strategy-2-maker.botsettings-ref .portfolio-tp-row>span{display:grid;gap:1px;font-size:8px} #strategy-2-maker.botsettings-ref .portfolio-tp-row>span b{font-size:10px} #strategy-2-maker.botsettings-ref .portfolio-tp-row em{grid-column:1/-1;color:#ffc18f;font-size:8px;font-style:normal} #strategy-2-maker.botsettings-ref .tp-off-note{margin:0;padding:5px 6px;border-radius:8px;background:rgba(255,255,255,.03);font-size:8.5px;opacity:.8}
      #strategy-2-maker.botsettings-ref .smart-rescue-card{grid-column:1/-1;border:1px solid rgba(92,119,108,.28);border-radius:13px;background:linear-gradient(180deg,rgba(8,17,14,.96),rgba(3,8,7,.98));overflow:hidden;transition:.2s ease} #strategy-2-maker.botsettings-ref .smart-rescue-card.enabled{border-color:rgba(33,214,154,.45);box-shadow:inset 0 1px rgba(255,255,255,.025),0 10px 28px rgba(0,0,0,.22)}
      #strategy-2-maker.botsettings-ref .smart-rescue-toggle{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:0;padding:9px 10px} #strategy-2-maker.botsettings-ref .smart-rescue-toggle>span{display:grid;gap:1px} #strategy-2-maker.botsettings-ref .smart-rescue-toggle small{font-size:7px;letter-spacing:.14em;color:var(--gold)} #strategy-2-maker.botsettings-ref .smart-rescue-toggle b{font-size:12px;color:#eaf7f1} #strategy-2-maker.botsettings-ref .smart-rescue-toggle em{font-size:8px;color:#8d9b94;font-style:normal} #strategy-2-maker.botsettings-ref .smart-rescue-toggle input{width:34px;height:20px;accent-color:var(--green)}
      #strategy-2-maker.botsettings-ref .smart-rescue-body{display:grid;gap:7px;padding:0 9px 9px} #strategy-2-maker.botsettings-ref .smart-rescue-note{margin:0;padding:6px 7px;border-radius:8px;background:rgba(33,214,154,.055);font-size:8px;line-height:1.35;color:#aebbb5} #strategy-2-maker.botsettings-ref .smart-rescue-note b{color:#d9eee4}
      #strategy-2-maker.botsettings-ref .smart-rescue-fields{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:5px} #strategy-2-maker.botsettings-ref .smart-rescue-fields label{font-size:8px;margin:0;gap:2px}
      #strategy-2-maker.botsettings-ref .smart-rescue-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px} #strategy-2-maker.botsettings-ref .smart-rescue-summary>div{display:grid;gap:2px;padding:6px;border:1px solid rgba(33,214,154,.16);border-radius:9px;background:rgba(0,0,0,.18)} #strategy-2-maker.botsettings-ref .smart-rescue-summary small{font-size:6.5px;color:#718078;letter-spacing:.08em} #strategy-2-maker.botsettings-ref .smart-rescue-summary b{font-size:9px;color:#d8ece2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      #strategy-2-maker.botsettings-ref .smart-rescue-chart{border:1px solid rgba(33,214,154,.18);border-radius:11px;background:radial-gradient(circle at 72% 20%,rgba(33,214,154,.07),transparent 38%),#040a08;padding:5px;overflow:hidden} #strategy-2-maker.botsettings-ref .smart-rescue-chart svg{display:block;width:100%;height:auto;max-height:190px}
      #strategy-2-maker.botsettings-ref .smart-rescue-risk{display:grid;gap:6px;padding:7px;border:1px solid rgba(33,214,154,.20);border-radius:10px;background:rgba(33,214,154,.035)} #strategy-2-maker.botsettings-ref .smart-rescue-risk.warn{border-color:rgba(230,184,74,.42);background:rgba(230,184,74,.045)} #strategy-2-maker.botsettings-ref .smart-rescue-risk.high,#strategy-2-maker.botsettings-ref .smart-rescue-risk.danger{border-color:rgba(255,120,146,.50);background:rgba(255,120,146,.055)} #strategy-2-maker.botsettings-ref .risk-head{display:flex;justify-content:space-between;align-items:center;gap:8px} #strategy-2-maker.botsettings-ref .risk-head span{display:grid;gap:1px} #strategy-2-maker.botsettings-ref .risk-head small{font-size:6.5px;letter-spacing:.1em;color:#7f8d86} #strategy-2-maker.botsettings-ref .risk-head b{font-size:9px} #strategy-2-maker.botsettings-ref .risk-head strong{font-size:15px;color:#82e7b8}
      #strategy-2-maker.botsettings-ref .risk-bars{display:grid;gap:4px} #strategy-2-maker.botsettings-ref .risk-bars label{display:grid;grid-template-columns:92px 1fr auto;align-items:center;gap:5px;font-size:7px} #strategy-2-maker.botsettings-ref .risk-bars i{display:block;height:5px;border-radius:999px;background:rgba(255,255,255,.06);overflow:hidden} #strategy-2-maker.botsettings-ref .risk-bars u{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,rgba(33,214,154,.65),rgba(214,181,90,.85));text-decoration:none} #strategy-2-maker.botsettings-ref .risk-bars b{font-size:7px}
      #strategy-2-maker.botsettings-ref .stress-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px} #strategy-2-maker.botsettings-ref .stress-grid span{display:grid;padding:5px;border-radius:7px;background:rgba(255,255,255,.025)} #strategy-2-maker.botsettings-ref .stress-grid small{font-size:6px;color:#76837d} #strategy-2-maker.botsettings-ref .stress-grid b{font-size:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis} #strategy-2-maker.botsettings-ref .smart-rescue-risk p{margin:0;font-size:7.5px;line-height:1.35;color:#d5b8ae}
      #strategy-2-maker.botsettings-ref .smart-rescue-live{border:1px solid rgba(33,214,154,.16);border-radius:9px;background:rgba(33,214,154,.025);overflow:hidden} #strategy-2-maker.botsettings-ref .smart-rescue-live summary{display:flex;justify-content:space-between;align-items:center;cursor:pointer;list-style:none;padding:6px 7px;font-size:8px;font-weight:800;color:#bfe8d3} #strategy-2-maker.botsettings-ref .smart-rescue-live summary span{min-width:18px;text-align:center;padding:2px 5px;border-radius:999px;background:rgba(33,214,154,.12);color:#8ef0c4} #strategy-2-maker.botsettings-ref .smart-live-list{display:grid;gap:5px;padding:0 6px 6px} #strategy-2-maker.botsettings-ref .smart-live-list article{display:grid;gap:5px;padding:6px;border-radius:8px;background:rgba(0,0,0,.22);border:1px solid rgba(255,255,255,.04)} #strategy-2-maker.botsettings-ref .smart-live-list header{display:flex;justify-content:space-between;align-items:center;gap:6px} #strategy-2-maker.botsettings-ref .smart-live-list header b{font-size:9px;color:#e5f4ec} #strategy-2-maker.botsettings-ref .smart-live-list header em{font-size:6.5px;font-style:normal;color:#7ce7b5} #strategy-2-maker.botsettings-ref .smart-live-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:3px} #strategy-2-maker.botsettings-ref .smart-live-grid span{display:grid;gap:1px;padding:4px;border-radius:6px;background:rgba(255,255,255,.02);min-width:0} #strategy-2-maker.botsettings-ref .smart-live-grid small{font-size:5.8px;color:#75847d} #strategy-2-maker.botsettings-ref .smart-live-grid b{font-size:7.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis} #strategy-2-maker.botsettings-ref .smart-live-next{display:grid;grid-template-columns:auto 1fr;gap:2px 6px;align-items:center;font-size:7px} #strategy-2-maker.botsettings-ref .smart-live-next span{color:#77867f} #strategy-2-maker.botsettings-ref .smart-live-next b{text-align:right;color:#cce9da} #strategy-2-maker.botsettings-ref .smart-live-next em{grid-column:1/-1;font-size:6.5px;font-style:normal;color:#9bb1a6} #strategy-2-maker.botsettings-ref .smart-live-list article>small{font-size:6px;line-height:1.3;color:#6f7d76}
      #strategy-2-maker.botsettings-ref .smart-rescue-details{border-top:1px solid rgba(255,255,255,.05);padding-top:4px} #strategy-2-maker.botsettings-ref .smart-rescue-details summary{display:flex;justify-content:space-between;cursor:pointer;list-style:none;padding:5px 2px;color:#b8c8c0;font-size:8px;font-weight:800} #strategy-2-maker.botsettings-ref .smart-rescue-table-wrap{overflow:auto;border:1px solid rgba(255,255,255,.06);border-radius:8px} #strategy-2-maker.botsettings-ref .smart-rescue-table-wrap table{width:max-content;min-width:100%;border-collapse:collapse;font-size:7px} #strategy-2-maker.botsettings-ref .smart-rescue-table-wrap th,#strategy-2-maker.botsettings-ref .smart-rescue-table-wrap td{padding:5px 6px;border-bottom:1px solid rgba(255,255,255,.045);white-space:nowrap;text-align:right} #strategy-2-maker.botsettings-ref .smart-rescue-table-wrap th:first-child,#strategy-2-maker.botsettings-ref .smart-rescue-table-wrap td:first-child{text-align:left;position:sticky;left:0;background:#07100d} #strategy-2-maker.botsettings-ref .smart-rescue-table-wrap th{color:#829088;font-size:6px;letter-spacing:.05em} #strategy-2-maker.botsettings-ref .smart-rescue-disclaimer{display:block;margin-top:5px;font-size:6.5px;line-height:1.35;color:#75817b}
      #strategy-2-maker.botsettings-ref .manual-symbol-toggle{grid-column:1/-1;min-height:41px;margin:0;padding:6px 8px;border-radius:10px;border:1px solid rgba(214,181,90,.22)} #strategy-2-maker.botsettings-ref .manual-symbol-toggle b{font-size:10px} #strategy-2-maker.botsettings-ref .manual-symbol-toggle small{font-size:8px;line-height:1.2}
      #strategy-2-maker.botsettings-ref .manual-symbol-picker{grid-column:1/-1;margin:0} #strategy-2-maker.botsettings-ref .maker-nav{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px;margin-top:7px;padding-bottom:max(3px,env(safe-area-inset-bottom))} #strategy-2-maker.botsettings-ref .maker-nav button{min-height:36px;padding:6px;border-radius:9px;font-size:8.5px;line-height:1.12} #strategy-2-maker.botsettings-ref .maker-nav button:first-child{border-color:rgba(33,214,154,.55);background:linear-gradient(180deg,rgba(33,214,154,.18),rgba(33,214,154,.07))}
      @media(max-width:430px){#strategy-2-maker.botsettings-ref{padding:9px;border-radius:14px}#strategy-2-maker.botsettings-ref .smart-rescue-fields,#strategy-2-maker.botsettings-ref .smart-rescue-summary{grid-template-columns:1fr 1fr}#strategy-2-maker.botsettings-ref .stress-grid,#strategy-2-maker.botsettings-ref .smart-live-grid{grid-template-columns:1fr 1fr}#strategy-2-maker.botsettings-ref .risk-bars label{grid-template-columns:78px 1fr auto}#strategy-2-maker.botsettings-ref .side-settings-head{grid-template-columns:1fr}#strategy-2-maker.botsettings-ref .tp-tabs{width:100%}#strategy-2-maker.botsettings-ref .portfolio-tp-row{grid-template-columns:1fr 1fr}#strategy-2-maker.botsettings-ref .side-columns{gap:4px}#strategy-2-maker.botsettings-ref .side-card{padding:5px}#strategy-2-maker.botsettings-ref .compact-settings-grid input{height:31px;font-size:11px}}
      @media(max-width:350px){#strategy-2-maker.botsettings-ref .side-columns{grid-template-columns:1fr}#strategy-2-maker.botsettings-ref .maker-nav{grid-template-columns:1fr}}
    `}</style>
  </article>;
}

function SmartRescueChart({ rows, current, breakEven, recovery }: { rows: SmartPreviewRow[]; current: number; breakEven: number; recovery: number }) {
  const prices = [100, current, breakEven, ...rows.map((row) => row.trigger)].filter((value) => Number.isFinite(value));
  const min = Math.min(...prices) - 1; const max = Math.max(...prices) + 1; const y = (price: number) => 138 - ((price - min) / Math.max(.0001, max - min)) * 105;
  const currentY = y(current); const beY = y(breakEven);
  const points = rows.map((row, idx) => `${28 + (idx / Math.max(1, rows.length - 1)) * 205},${y(row.trigger)}`).join(" ");
  return <svg viewBox="0 0 330 160" role="img" aria-label={`Nog ${recovery.toFixed(2)} procent koersherstel naar break-even`}>
    <line x1="18" y1={y(100)} x2="312" y2={y(100)} stroke="rgba(214,181,90,.35)" strokeDasharray="4 4" /><text x="20" y={y(100)-4} fill="#b79c51" fontSize="7">START 100</text>
    {points && <polyline points={points} fill="none" stroke="rgba(80,145,255,.62)" strokeWidth="1.5" />}
    {rows.map((row, idx) => <circle key={row.index} cx={28 + (idx / Math.max(1, rows.length - 1)) * 205} cy={y(row.trigger)} r="2.4" fill="#5599ff" />)}
    <line x1="18" y1={beY} x2="312" y2={beY} stroke="#21d69a" strokeWidth="1.4" strokeDasharray="5 4" /><text x="20" y={beY-4} fill="#72e8b6" fontSize="7">BREAK-EVEN {breakEven.toFixed(4)}</text>
    <circle cx="250" cy={currentY} r="3.5" fill="#ff7892" /><text x="256" y={currentY+2} fill="#ff96aa" fontSize="7">NU {current.toFixed(4)}</text>
    <line x1="286" y1={currentY} x2="286" y2={beY} stroke="#21d69a" strokeWidth="2" /><path d={`M282 ${beY+5} L286 ${beY} L290 ${beY+5}`} fill="none" stroke="#21d69a" strokeWidth="1.5" />
    <rect x="195" y="143" width="117" height="13" rx="6" fill="rgba(33,214,154,.12)" /><text x="253.5" y="152" textAnchor="middle" fill="#9af1ca" fontSize="7.5" fontWeight="700">Nog +{recovery.toFixed(2)}% naar break-even</text>
  </svg>;
}

function Field({ label, value, set, text = false, onBlur, disabled = false, suffix = "" }: { label: string; value: string; set: (value: string) => void; text?: boolean; onBlur?: () => void; disabled?: boolean; suffix?: string }) {
  return <label>{label}<span className="field-wrap" style={{ display: "flex", alignItems: "center", border: "1px solid rgba(214,181,90,.27)", borderRadius: 8, background: "rgba(0,0,0,.28)", overflow: "hidden", opacity: disabled ? .5 : 1 }}><input disabled={disabled} inputMode={text ? undefined : "decimal"} value={value} onChange={(event) => set(text ? event.target.value : event.target.value.replace(",", "."))} onBlur={onBlur} style={{ width: "100%", border: 0, background: "transparent", boxShadow: "none" }} />{suffix && <b style={{ paddingRight: 6, fontSize: 7.5, color: "#7e8a84" }}>{suffix}</b>}</span></label>;
}
