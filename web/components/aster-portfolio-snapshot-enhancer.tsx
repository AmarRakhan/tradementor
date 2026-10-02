"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { authenticatedRequest } from "@/lib/cloud-client";
import { AsterHedgeManager } from "./aster-hedge-manager";
import { PortfolioKoersChart } from "./portfolio-koers-chart";
import { PortfolioPerformanceDetail, type PerformanceInitialTab } from "./portfolio-performance-detail";
import { formatLiquidationRisk, liquidationNeedleDegrees, liquidationRiskRemaining, liquidationRiskTone, normalizeLiquidationRisk } from "@/lib/liquidation-gauge.mjs";

type Tone = "positive" | "negative" | "neutral";
type ProfitScope = "LONG" | "SHORT" | "ALL";
type HedgeStatus = "below_target" | "within_target" | "above_target" | "unavailable";
type ImpactType = "toward_target" | "away_from_target" | "neutral";
type ProtectionDirection = "increases" | "decreases" | "unchanged";

type SnapshotValues = {
  equity: string;
  available: string;
  activeCapital: string;
  activePositions: string;
  realized: string;
  tradesClosed: string;
  longs: string;
  shorts: string;
  longCapacity: string;
  shortCapacity: string;
  dca: string;
  liquidation: string;
  todayGrowth: string;
  averageDailyGrowth: string;
  realizedTone: Tone;
  todayGrowthTone: Tone;
  averageDailyGrowthTone: Tone;
  riskTone: "safe" | "caution" | "high" | "critical" | "unknown";
  closeDisabled: boolean;
  closeBusy: boolean;
};

type ExposureSnapshot = {
  reliable: boolean;
  longExposureUsd: number;
  shortExposureUsd: number;
  netExposureUsd: number;
  netSide: "LONG" | "SHORT" | "FLAT";
  hedgeCoveragePercent: number | null;
  status: HedgeStatus;
  openPositionCount: number;
  invalidOpenCount: number;
};

type CloseImpact = {
  before: ExposureSnapshot;
  after: ExposureSnapshot;
  removedLongExposureUsd: number;
  removedShortExposureUsd: number;
  impactType: ImpactType;
  protectionDirection: ProtectionDirection;
  targetDistanceBefore: number | null;
  targetDistanceAfter: number | null;
};

type ProfitBucket = {
  eligibleCount: number;
  totalProfitUsd: number;
  impact: CloseImpact;
};

type HedgeConfig = {
  targetPercent: number;
  healthyMinPercent: number;
  healthyMaxPercent: number;
};

type ProfitPreview = {
  reliable: true;
  minimumProfitUsd: number;
  comparison: "greater_than_or_equal";
  hedgeConfig: HedgeConfig;
  exposure: ExposureSnapshot;
  long: ProfitBucket;
  short: ProfitBucket;
  all: ProfitBucket;
};

const EMPTY: SnapshotValues = {
  equity: "—", available: "—", activeCapital: "—", activePositions: "—",
  realized: "—", tradesClosed: "—", longs: "—", shorts: "—", longCapacity: "—", shortCapacity: "—", dca: "—",
  liquidation: "—", todayGrowth: "—", averageDailyGrowth: "—",
  realizedTone: "neutral", todayGrowthTone: "neutral", averageDailyGrowthTone: "neutral", riskTone: "unknown",
  closeDisabled: true, closeBusy: false,
};

const REFERENCE = "file_000000002444821084b234da2ddec369";
const HEDGE_DETAIL_REFERENCE = "file_00000000032881f495cdc99757a7d126";
const HEDGE_CARD_REFERENCE = "file_00000000aa6c8210baf1b0ac8f94d18e";
const CLOSE_RISK_REFERENCE = "file_000000006ef082468c8b3f46e9a0057b";
const CLOSE_POSITIVE_REFERENCE = "file_000000009fec821084026a5551398488";
const LIQUIDATION_GAUGE_REFERENCE = "file_000000004e80820a80318a3de3ae5abd";
const SNAPSHOT_V2_REFERENCE = "file_0000000061fc81f49a44564879d533de";
const SNAPSHOT_DETAIL_BUTTONS_REFERENCE = "file_00000000afb481f480fb60893b473c16";
const PRICE_ZONE_DETAILS_REFERENCE = "file_00000000a63481f493d2f56071aaeb3b";
const SCANNER_STATUS_REFERENCE = "file_000000002d908210a581e71c2352d09b";

type LiquidationDiagnostics = {
  liquidationRiskPercent: number | null;
  source: "ASTER_ACCOUNT_RATIO" | "SERVER_RECONSTRUCTED" | "UNKNOWN";
  marginBalance: number | null;
  equity: number | null;
  maintenanceMarginUsd: number | null;
  longExposureUsd: number | null;
  shortExposureUsd: number | null;
  netExposureUsd: number | null;
};

type PriceZoneSeatSummary = {
  enabled: boolean;
  runtimeTruthCanonical: boolean;
  activeZone: number | null;
  perZoneLong: number;
  perZoneShort: number;
  freeLongActiveZone: number;
  freeShortActiveZone: number;
  occupiedLongActiveZone: number;
  occupiedShortActiveZone: number;
  openFromOldZones: number;
  maxTotal: number;
  strategyOpenLong: number;
  strategyOpenShort: number;
  strategyOpenTotal: number;
  zoneOpenCounts: Record<string, { long: number; short: number; total: number }>;
  zoneOpenCountsReliable: boolean;
  entryStatus: string;
  entryReason: string;
  entrySkipReasons: Record<string, number>;
  zoneMigrationHold: boolean;
  dynamicHedgeEnabled: boolean;
  dynamicHedgeBlocking: boolean;
  dynamicHedgeOwnershipState: string;
  dynamicHedgeReason: string;
  dynamicHedgeSafetyStatus: string;
  queueHaltedUncertain: boolean;
  queueUncertainReason: string;
};

type SnapshotDetailView = "portfolio" | "price-zone" | "scanner" | "performance";
type ScannerVerdict = "NORMAAL" | "GEEN KANDIDATEN" | "GEBLOKKEERD" | "SCANNER STIL" | "ORDERFOUT";

type ScannerSideStatus = {
  timeframe: string;
  marketsScanned: number | null;
  bbCandidates: number | null;
  zoneAllowed: number | null;
  blockedFilters: number | null;
  ordersPlaced: number | null;
  lastEntryAtMs: number | null;
  availableCapacity: number | null;
};

type ScannerStatusSnapshot = {
  enabled: boolean;
  monitor: boolean;
  updatedAtMs: number | null;
  entryStatus: string;
  entryReason: string;
  unscopedBlocked: number | null;
  long: ScannerSideStatus;
  short: ScannerSideStatus;
};

function directText(element: Element | null, selector: string) {
  return element?.querySelector<HTMLElement>(selector)?.textContent?.trim() || "—";
}

function metric(label: string) {
  const rows = Array.from(document.querySelectorAll<HTMLElement>(".metric-strip .metric"));
  const row = rows.find((item) => item.querySelector("span")?.textContent?.trim().toUpperCase() === label);
  return row ? directText(row, "strong") : "—";
}

function slotCount(side: "long" | "short") {
  const row = document.querySelector<HTMLElement>(`.slot-overview .slot-row.${side}`);
  const countText = row?.querySelector<HTMLElement>("b")?.textContent || "";
  const match = countText.match(/(\d+)\s*\/\s*(\d+)/);
  return { active: match?.[1] || "", capacity: match?.[2] || "" };
}

function percentageTone(value: string): Tone {
  if (value === "—") return "neutral";
  const parsed = Number(value.replace("%", "").replace("+", "").replace(",", ".").trim());
  return Number.isFinite(parsed) && parsed > 0 ? "positive" : Number.isFinite(parsed) && parsed < 0 ? "negative" : "neutral";
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

function optionalNumber(value: unknown) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function firstNumber(records: Record<string, unknown>[], keys: string[]) {
  for (const source of records) {
    for (const key of keys) {
      const value = optionalNumber(source[key]);
      if (value !== null) return value;
    }
  }
  return null;
}

function firstString(records: Record<string, unknown>[], keys: string[]) {
  for (const source of records) {
    for (const key of keys) {
      const value = source[key];
      if (typeof value === "string" && value.trim()) return value.trim();
    }
  }
  return "";
}

function timestampMs(value: unknown) {
  const numeric = optionalNumber(value);
  if (numeric !== null) return numeric > 0 && numeric < 10_000_000_000 ? numeric * 1000 : numeric;
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function money(value: number | null, fallback = "—") {
  if (value === null || !Number.isFinite(value)) return fallback;
  return `US$ ${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)}`;
}

async function loadLiquidationDiagnostics(): Promise<LiquidationDiagnostics> {
  const payload = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" });
  const root = record(payload);
  const records = [root, record(root.data), record(root.account), record(root.snapshot), record(root.accountRisk), record(root.crossRisk), record(root.portfolio)];
  const sourceRaw = firstString(records, ["liquidationRiskSource"]);
  const source = sourceRaw === "ASTER_ACCOUNT_RATIO" || sourceRaw === "SERVER_RECONSTRUCTED" ? sourceRaw : "UNKNOWN";
  return {
    liquidationRiskPercent: firstNumber(records, ["liquidationRiskPct"]),
    source,
    marginBalance: firstNumber(records, ["marginBalance", "totalMarginBalance"]),
    equity: firstNumber(records, ["equity", "totalMarginBalance"]),
    maintenanceMarginUsd: firstNumber(records, ["maintenanceMarginUsd", "totalMaintMargin"]),
    longExposureUsd: firstNumber(records, ["longNotional", "longExposureUsd"]),
    shortExposureUsd: firstNumber(records, ["shortNotional", "shortExposureUsd"]),
    netExposureUsd: firstNumber(records, ["netExposure", "netExposureUsd"]),
  };
}

async function loadPriceZoneSeatSummary(): Promise<PriceZoneSeatSummary> {
  const payload = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" });
  const root = record(payload);
  const strategy2 = Object.keys(record(root.strategy2)).length
    ? record(root.strategy2)
    : Object.keys(record(record(root.data).strategy2)).length
      ? record(record(root.data).strategy2)
      : record(record(root.snapshot).strategy2);
  const settings = record(strategy2.settings);
  const runtimeTruth = record(strategy2.runtimeTruth);
  const runtimeTruthCanonical = runtimeTruth.source === "SERVER_RUNTIME";
  const entryDiagnostics = record(strategy2.entryDiagnostics);
  const dynamicHedge = record(entryDiagnostics.dynamicHedge);
  const queue = record(entryDiagnostics.queue);
  const seatReport = Object.keys(record(strategy2.priceZoneSeats)).length
    ? record(strategy2.priceZoneSeats)
    : record(strategy2.zoneSoldiers);
  const seatModel = record(seatReport.seatModel);
  const currentZone = record(seatReport.currentZone);
  const oldZones = record(seatReport.oldZonesOpen);
  const strategyOwned = record(seatReport.strategyOwnedOpen);
  const perZoneLong = Math.max(1, Math.round(firstNumber([seatModel, settings], ["perZoneLong", "zoneBaseLongSoldiers"]) ?? 3));
  const perZoneShort = Math.max(1, Math.round(firstNumber([seatModel, settings], ["perZoneShort", "zoneBaseShortSoldiers"]) ?? 3));
  const activeZoneNumber = firstNumber(runtimeTruthCanonical ? [runtimeTruth, seatModel, seatReport] : [seatModel, seatReport], ["activeZone"]);
  const activeOpenLong = Math.max(0, Math.round(firstNumber([seatModel, currentZone], ["occupiedLongActiveZone", "openLong"]) ?? 0));
  const activeOpenShort = Math.max(0, Math.round(firstNumber([seatModel, currentZone], ["occupiedShortActiveZone", "openShort"]) ?? 0));
  const strategyOpenLong = Math.max(0, Math.round(firstNumber([seatModel, strategyOwned], ["strategyOpenLong", "long"]) ?? 0));
  const strategyOpenShort = Math.max(0, Math.round(firstNumber([seatModel, strategyOwned], ["strategyOpenShort", "short"]) ?? 0));
  const maxTotal = Math.max(1, Math.round(firstNumber(runtimeTruthCanonical ? [runtimeTruth, settings] : [settings], ["maximumPositions"]) ?? (perZoneLong + perZoneShort)));

  let zoneOpenCounts: Record<string, { long: number; short: number; total: number }> = {};
  for (const [rawZone, rawCounts] of Object.entries(record(seatReport.zoneOpenCounts))) {
    const zone = Number(rawZone);
    if (!Number.isInteger(zone)) continue;
    const counts = record(rawCounts);
    const long = Math.max(0, Math.round(optionalNumber(counts.long) ?? 0));
    const short = Math.max(0, Math.round(optionalNumber(counts.short) ?? 0));
    const total = Math.max(0, Math.round(optionalNumber(counts.total) ?? (long + short)));
    zoneOpenCounts[String(zone)] = { long, short, total };
  }
  const zoneTotals = () => Object.values(zoneOpenCounts).reduce(
    (sum, row) => ({ long: sum.long + row.long, short: sum.short + row.short, total: sum.total + row.total }),
    { long: 0, short: 0, total: 0 },
  );
  let zoneOpenCountsReliable = seatReport.zoneOpenCountsReliable === true;
  let totals = zoneTotals();
  zoneOpenCountsReliable = zoneOpenCountsReliable
    && totals.long === strategyOpenLong
    && totals.short === strategyOpenShort
    && totals.total === strategyOpenLong + strategyOpenShort;

  // Backward-compatible bridge while backend/web releases overlap: derive the
  // same per-zone breakdown from managed Strategy-2 ownership only when its
  // totals exactly match the exchange-confirmed seat report. This never guesses.
  if (!zoneOpenCountsReliable) {
    const derived: Record<string, { long: number; short: number; total: number }> = {};
    for (const [tradeKey, rawManaged] of Object.entries(record(strategy2.multiBbPositions))) {
      const managed = record(rawManaged);
      const role = String(managed.soldierRole || "").toUpperCase();
      if (role !== "ZONE_BASE" && role !== "EXPOSURE_BALANCER") continue;
      const originZone = optionalNumber(managed.originZone);
      if (originZone === null || !Number.isInteger(originZone)) continue;
      const keySide = tradeKey.toUpperCase();
      const side = String(managed.side || managed.positionSide || (keySide.endsWith("|LONG") ? "LONG" : keySide.endsWith("|SHORT") ? "SHORT" : "")).toUpperCase();
      if (side !== "LONG" && side !== "SHORT") continue;
      const zoneKey = String(Math.round(originZone));
      const bucket = derived[zoneKey] || { long: 0, short: 0, total: 0 };
      if (side === "LONG") bucket.long += 1;
      else bucket.short += 1;
      bucket.total += 1;
      derived[zoneKey] = bucket;
    }
    const derivedTotals = Object.values(derived).reduce(
      (sum, row) => ({ long: sum.long + row.long, short: sum.short + row.short, total: sum.total + row.total }),
      { long: 0, short: 0, total: 0 },
    );
    if (
      derivedTotals.long === strategyOpenLong
      && derivedTotals.short === strategyOpenShort
      && derivedTotals.total === strategyOpenLong + strategyOpenShort
    ) {
      zoneOpenCounts = derived;
      totals = derivedTotals;
      zoneOpenCountsReliable = true;
    }
  }

  return {
    enabled: runtimeTruthCanonical
      ? runtimeTruth.strategyMode === "ZONE_WARRIORS" && runtimeTruth.enabled === true
      : seatReport.enabled === true && settings.zoneSoldiersEnabled === true,
    runtimeTruthCanonical,
    activeZone: activeZoneNumber === null ? null : Math.round(activeZoneNumber),
    perZoneLong,
    perZoneShort,
    freeLongActiveZone: Math.max(0, Math.round(firstNumber([seatModel], ["freeLongActiveZone"]) ?? (perZoneLong - activeOpenLong))),
    freeShortActiveZone: Math.max(0, Math.round(firstNumber([seatModel], ["freeShortActiveZone"]) ?? (perZoneShort - activeOpenShort))),
    occupiedLongActiveZone: activeOpenLong,
    occupiedShortActiveZone: activeOpenShort,
    openFromOldZones: Math.max(0, Math.round(firstNumber([seatModel, oldZones], ["openFromOldZones", "total"]) ?? 0)),
    maxTotal,
    strategyOpenLong,
    strategyOpenShort,
    strategyOpenTotal: Math.max(0, Math.round(firstNumber([seatModel, strategyOwned], ["strategyOpenTotal", "total"]) ?? (strategyOpenLong + strategyOpenShort))),
    zoneOpenCounts,
    zoneOpenCountsReliable,
    entryStatus: firstString(runtimeTruthCanonical ? [runtimeTruth, entryDiagnostics] : [entryDiagnostics], ["entryStatus"]),
    entryReason: firstString(runtimeTruthCanonical ? [runtimeTruth, entryDiagnostics] : [entryDiagnostics], ["entryReason", "lastReason"]),
    entrySkipReasons: record(entryDiagnostics.entrySkipReasons) as Record<string, number>,
    zoneMigrationHold: entryDiagnostics.zoneMigrationHold === true,
    dynamicHedgeEnabled: dynamicHedge.enabled === true,
    dynamicHedgeBlocking: runtimeTruthCanonical ? runtimeTruth.dynamicHedgeBlocking === true : dynamicHedge.blocking === true,
    dynamicHedgeOwnershipState: firstString([dynamicHedge], ["ownershipState"]),
    dynamicHedgeReason: firstString([dynamicHedge], ["reason"]),
    dynamicHedgeSafetyStatus: firstString([dynamicHedge], ["safetyStatus"]),
    queueHaltedUncertain: runtimeTruthCanonical ? runtimeTruth.queueHalted === true : queue.haltedUncertain === true,
    queueUncertainReason: firstString([queue], ["uncertainReason"]),
  };
}

function scannerSideStatus(rawSide: Record<string, unknown>): ScannerSideStatus {
  const nonNegativeInteger = (key: string) => {
    const value = optionalNumber(rawSide[key]);
    return value === null ? null : Math.max(0, Math.round(value));
  };
  return {
    timeframe: firstString([rawSide], ["timeframe"]) || "—",
    marketsScanned: nonNegativeInteger("marketsScanned"),
    bbCandidates: nonNegativeInteger("bbCandidates"),
    zoneAllowed: nonNegativeInteger("zoneAllowed"),
    blockedFilters: nonNegativeInteger("blockedFilters"),
    ordersPlaced: nonNegativeInteger("ordersPlaced"),
    lastEntryAtMs: optionalNumber(rawSide.lastEntryAtMs),
    availableCapacity: nonNegativeInteger("availableCapacity"),
  };
}

async function loadScannerStatus(): Promise<ScannerStatusSnapshot> {
  const payload = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" });
  const root = record(payload);
  const strategy2 = Object.keys(record(root.strategy2)).length
    ? record(root.strategy2)
    : Object.keys(record(record(root.data).strategy2)).length
      ? record(record(root.data).strategy2)
      : record(record(root.snapshot).strategy2);
  const runtimeTruth = record(strategy2.runtimeTruth);
  const runtimeTruthCanonical = runtimeTruth.source === "SERVER_RUNTIME";
  const multiBb = record(strategy2.multiBb);
  const scanner = record(runtimeTruthCanonical ? runtimeTruth.scannerDiagnostics : multiBb.scannerDiagnostics);
  return {
    enabled: runtimeTruthCanonical ? runtimeTruth.enabled === true : strategy2.enabled === true,
    monitor: runtimeTruthCanonical ? runtimeTruth.monitor === true : strategy2.monitor === true,
    updatedAtMs: firstNumber([scanner, multiBb], ["updatedAtMs"]) ?? (runtimeTruthCanonical ? timestampMs(runtimeTruth.lastTickAt) : null),
    entryStatus: firstString(runtimeTruthCanonical ? [runtimeTruth, multiBb, record(strategy2.entryDiagnostics)] : [multiBb, record(strategy2.entryDiagnostics)], ["entryStatus"]),
    entryReason: firstString(runtimeTruthCanonical ? [runtimeTruth, multiBb, record(strategy2.entryDiagnostics)] : [multiBb, record(strategy2.entryDiagnostics)], ["entryReason"]),
    unscopedBlocked: optionalNumber(scanner.unscopedBlocked),
    long: scannerSideStatus(record(scanner.LONG)),
    short: scannerSideStatus(record(scanner.SHORT)),
  };
}

function readSnapshot(): SnapshotValues {
  const realizedRow = Array.from(document.querySelectorAll<HTMLElement>(".metric-strip .metric")).find((item) =>
    item.querySelector("span")?.textContent?.trim().toUpperCase() === "GESLOTEN RESULTAAT VANDAAG",
  );
  const realized = realizedRow ? directText(realizedRow, "strong") : "—";
  const tradesClosed = directText(document.querySelector(".realized-trades-count"), "strong");
  const indexSummary = document.querySelector<HTMLElement>(".active-trades-index > small")?.textContent || "";
  const counts = indexSummary.match(/(\d+)\s*posities\s*·\s*(\d+)L\s*\/\s*(\d+)S\s*·\s*(\d+)\s*DCA/i);
  const longSlots = slotCount("long");
  const shortSlots = slotCount("short");
  const risk = document.querySelector<HTMLElement>(".liquidation-risk");
  const riskClass = risk?.className || "";
  const closeButton = document.querySelector<HTMLButtonElement>(".portfolio-close-all");
  const dailyGrowth = document.querySelector<HTMLElement>(".portfolio-growth-daily");
  const dailyValues = dailyGrowth ? Array.from(dailyGrowth.querySelectorAll<HTMLElement>("strong")) : [];
  const todayGrowth = dailyValues[0]?.textContent?.trim() || "—";
  const averageDailyGrowth = dailyValues[1]?.textContent?.trim() || "—";
  return {
    equity: metric("PORTFOLIOWAARDE"),
    available: metric("AVAILABLE TO TRADE"),
    activeCapital: metric("ACTIVE TRADE CAPITAL"),
    activePositions: metric("ACTIEVE POSITIES"),
    realized,
    tradesClosed,
    longs: longSlots.active || counts?.[2] || "—",
    shorts: shortSlots.active || counts?.[3] || "—",
    longCapacity: longSlots.capacity || "—",
    shortCapacity: shortSlots.capacity || "—",
    dca: counts?.[4] || "—",
    liquidation: directText(risk, ".risk-core strong"),
    todayGrowth,
    averageDailyGrowth,
    realizedTone: realizedRow?.classList.contains("positive") ? "positive" : realizedRow?.classList.contains("negative") ? "negative" : "neutral",
    todayGrowthTone: percentageTone(todayGrowth),
    averageDailyGrowthTone: percentageTone(averageDailyGrowth),
    riskTone: riskClass.includes("risk-safe") ? "safe" : riskClass.includes("risk-caution") ? "caution" : riskClass.includes("risk-high") ? "high" : riskClass.includes("risk-critical") ? "critical" : "unknown",
    closeDisabled: !closeButton || closeButton.disabled,
    closeBusy: Boolean(closeButton && /sluiten…|bezig|wachten/i.test(closeButton.textContent || "")),
  };
}

function valuesEqual(a: SnapshotValues, b: SnapshotValues) {
  return Object.keys(a).every((key) => a[key as keyof SnapshotValues] === b[key as keyof SnapshotValues]);
}

function Icon({ name }: { name: "wallet" | "coins" | "capital" | "positions" | "result" | "trades" | "balance" | "dca" | "shield" | "growth" | "calendar" }) {
  const common = { width: 27, height: 27, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };
  if (name === "wallet") return <svg {...common}><path d="M4 7.5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-11a2 2 0 0 1 2-2h12"/><path d="M15 12h6v4h-6a2 2 0 0 1 0-4Z"/></svg>;
  if (name === "coins") return <svg {...common}><ellipse cx="9" cy="6" rx="5" ry="2.5"/><path d="M4 6v4c0 1.4 2.2 2.5 5 2.5s5-1.1 5-2.5V6M4 10v4c0 1.4 2.2 2.5 5 2.5 1.2 0 2.3-.2 3.2-.6"/><ellipse cx="16.5" cy="15.5" rx="4.5" ry="2.3"/><path d="M12 15.5v3.2c0 1.3 2 2.3 4.5 2.3s4.5-1 4.5-2.3v-3.2"/></svg>;
  if (name === "capital") return <svg {...common}><circle cx="12" cy="12" r="8"/><path d="m12 12 4-4M12 12l-2 5"/></svg>;
  if (name === "positions") return <svg {...common}><path d="M5 19V13M10 19V8M15 19V11M20 19V4"/></svg>;
  if (name === "result") return <svg {...common}><path d="M3 5v14h18"/><path d="m5 9 4 4 4-6 6 5"/><path d="m16 12 3 .2-.2 3"/></svg>;
  if (name === "trades") return <svg {...common}><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8M8 11h8M8 15h5"/></svg>;
  if (name === "balance") return <svg {...common}><path d="m3 16 5-5 4 3 7-8"/><path d="M16 6h3v3"/></svg>;
  if (name === "dca") return <svg {...common}><path d="m12 3 7 4-7 4-7-4 7-4Z"/><path d="m5 11 7 4 7-4M5 15l7 4 7-4"/></svg>;
  if (name === "growth") return <svg {...common}><path d="M4 19V12M10 19V8M16 19V4"/><path d="M3 21h18"/></svg>;
  if (name === "calendar") return <svg {...common}><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18"/></svg>;
  return <svg {...common}><path d="M12 3 5 6v5c0 4.7 2.8 8.2 7 10 4.2-1.8 7-5.3 7-10V6l-7-3Z"/><path d="m9 12 2 2 4-5"/></svg>;
}

function MetricCard({ icon, label, value, tone = "normal", detail, detailTone = "muted" }: { icon: Parameters<typeof Icon>[0]["name"]; label: string; value: string; tone?: "normal" | "positive" | "negative"; detail?: string; detailTone?: "muted" | "positive" | "negative" }) {
  return <article className={`aps-metric aps-${tone}`}><span className="aps-icon"><Icon name={icon} /></span><div><small>{label}</small><strong>{value}</strong>{detail ? <em className={`aps-metric-detail aps-detail-${detailTone}`}>{detail}</em> : null}</div></article>;
}

function GrowthCard({ icon, label, value, tone, detail, onClick }: { icon: "growth" | "calendar"; label: string; value: string; tone: Tone; detail?: string; onClick?: () => void }) {
  return <button type="button" className={`aps-growth-card aps-${tone}`} onClick={onClick} aria-label={`${label}: ${value}. Open Rendement Overzicht.`}>
    <span className="aps-icon"><Icon name={icon} /></span>
    <span className="aps-growth-copy"><small>{label}</small><strong>{value}</strong>{detail ? <em className="aps-growth-detail">{detail}</em> : null}</span>
  </button>;
}


function LiquidationGauge({ value, diagnostics, exposure, equity, available }: {
  value: string;
  diagnostics: LiquidationDiagnostics | null;
  exposure: ExposureSnapshot | null | undefined;
  equity: string;
  available: string;
}) {
  const [flipped, setFlipped] = useState(false);
  const risk = normalizeLiquidationRisk(value);
  const degrees = liquidationNeedleDegrees(risk);
  const remaining = liquidationRiskRemaining(risk);
  const tone = liquidationRiskTone(risk);
  const display = formatLiquidationRisk(risk);
  const longExposure = exposure?.reliable ? exposure.longExposureUsd : diagnostics?.longExposureUsd ?? null;
  const shortExposure = exposure?.reliable ? exposure.shortExposureUsd : diagnostics?.shortExposureUsd ?? null;
  const netExposure = exposure?.reliable ? exposure.netExposureUsd : diagnostics?.netExposureUsd ?? null;
  const source = diagnostics?.source === "ASTER_ACCOUNT_RATIO" ? "ASTER ACCOUNT RATIO" : diagnostics?.source === "SERVER_RECONSTRUCTED" ? "SERVER RECONSTRUCTED" : "ONBEKEND";
  const marginLabel = diagnostics?.marginBalance !== null && diagnostics?.marginBalance !== undefined
    ? money(diagnostics.marginBalance)
    : diagnostics?.equity !== null && diagnostics?.equity !== undefined
      ? money(diagnostics.equity)
      : equity;

  return <button
    type="button"
    className={`aps-liquidation-gauge aps-gauge-${tone}`}
    data-reference={LIQUIDATION_GAUGE_REFERENCE}
    data-risk-value={risk ?? "unknown"}
    aria-label={`Liquidatierisico ${display}. Tik voor details.`}
    aria-pressed={flipped}
    onClick={() => setFlipped((current) => !current)}
  >
    <span className={`aps-gauge-flipper${flipped ? " is-flipped" : ""}`}>
      <span className="aps-gauge-face aps-gauge-front">
        <span className="aps-gauge-head"><b>LIQUIDATIERISICO</b><em><i />LIVE</em></span>
        <span className="aps-gauge-dial" aria-hidden="true">
          <svg viewBox="0 0 220 126" role="presentation">
            <path className="aps-gauge-track" d="M20 105 A90 90 0 0 1 200 105" pathLength="100" />
            <path className="aps-gauge-arc arc-green" d="M20 105 A90 90 0 0 1 200 105" pathLength="100" />
            <path className="aps-gauge-arc arc-lime" d="M20 105 A90 90 0 0 1 200 105" pathLength="100" />
            <path className="aps-gauge-arc arc-yellow" d="M20 105 A90 90 0 0 1 200 105" pathLength="100" />
            <path className="aps-gauge-arc arc-orange" d="M20 105 A90 90 0 0 1 200 105" pathLength="100" />
            <path className="aps-gauge-arc arc-red" d="M20 105 A90 90 0 0 1 200 105" pathLength="100" />
            <text x="21" y="119">0%</text>
            <text x="54" y="60">25%</text>
            <text x="110" y="39" textAnchor="middle">50%</text>
            <text x="166" y="60" textAnchor="middle">75%</text>
            <text x="199" y="119" textAnchor="end" className="danger">100%</text>
            <g className="aps-gauge-needle" style={{ transform: `rotate(${degrees}deg)`, transformOrigin: "110px 105px" }}>
              <line x1="110" y1="105" x2="37" y2="105" />
              <circle cx="110" cy="105" r="6" />
            </g>
            <circle className="aps-gauge-hub" cx="110" cy="105" r="3.2" />
          </svg>
        </span>
        <strong className="aps-gauge-value">{display}</strong>
        <small className="aps-gauge-caption">100% = liquidatie</small>
      </span>
      <span className="aps-gauge-face aps-gauge-back">
        <span className="aps-gauge-back-head"><b>LIQUIDATIERISICO</b><em>{display}</em></span>
        <span className="aps-gauge-details">
          <span><small>Ruimte tot 100%</small><strong>{remaining === null ? "—" : `${new Intl.NumberFormat("nl-NL", { maximumFractionDigits: 2 }).format(remaining)}%`}</strong></span>
          <span><small>Margin / equity</small><strong>{marginLabel}</strong></span>
          <span><small>Maintenance</small><strong>{money(diagnostics?.maintenanceMarginUsd ?? null)}</strong></span>
          <span><small>Available</small><strong>{available}</strong></span>
          <span><small>Long exposure</small><strong>{money(longExposure)}</strong></span>
          <span><small>Short exposure</small><strong>{money(shortExposure)}</strong></span>
          <span><small>Netto exposure</small><strong>{money(netExposure)}</strong></span>
          <span><small>Actuele ratio</small><strong>{diagnostics?.liquidationRiskPercent === null || diagnostics?.liquidationRiskPercent === undefined ? display : formatLiquidationRisk(diagnostics.liquidationRiskPercent)}</strong></span>
        </span>
        <small className="aps-gauge-source">BRON · {source}</small>
      </span>
    </span>
  </button>;
}

function profitMoney(value: number | undefined) {
  if (value === undefined || !Number.isFinite(value)) return "—";
  return `+US$ ${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Math.max(0, value))}`;
}

function exposureMoney(value: number | null | undefined, signed = false) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const prefix = signed ? (value > 0 ? "+" : value < 0 ? "-" : "") : "";
  return `${prefix}US$ ${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(Math.abs(value))}`;
}

function hedgePercent(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: Number.isInteger(value) ? 0 : 1, maximumFractionDigits: 1 }).format(value)}%`;
}

function hedgeStatusLabel(status: HedgeStatus) {
  if (status === "below_target") return "Onder doel";
  if (status === "above_target") return "Boven doel";
  if (status === "within_target") return "Binnen doel";
  return "Niet beschikbaar";
}

function netExposureLabel(exposure: ExposureSnapshot | null | undefined) {
  if (!exposure) return "—";
  if (exposure.netSide === "FLAT") return "NEUTRAAL";
  return exposure.netSide;
}

function impactNote(scope: ProfitScope, bucket: ProfitBucket | null) {
  if (!bucket?.impact || bucket.eligibleCount < 1) return null;
  if (bucket.impact.impactType === "toward_target") return "richting hedge-doel";
  if (bucket.impact.protectionDirection === "decreases") return "verlaagt hedge";
  if (bucket.impact.protectionDirection === "increases") return "verhoogt hedge";
  return scope === "ALL" ? "wijzigt bescherming" : null;
}

function ProfitAction({ scope, label, bucket, busy, onClick }: {
  scope: ProfitScope;
  label: string;
  bucket: ProfitBucket | null;
  busy: boolean;
  onClick: (scope: ProfitScope) => void;
}) {
  const count = bucket?.eligibleCount ?? 0;
  const countLabel = bucket ? `${count} ${count === 1 ? "positie" : "posities"}` : "—";
  const note = impactNote(scope, bucket);
  const icon = scope === "LONG" ? "↗" : scope === "SHORT" ? "↘" : "◎";
  return <button
    type="button"
    className={`aps-profit-action aps-profit-${scope.toLowerCase()}`}
    disabled={!bucket || count === 0 || busy}
    onClick={() => onClick(scope)}
    aria-label={`${label}, ${profitMoney(bucket?.totalProfitUsd)}, ${countLabel}${note ? `, ${note}` : ""}`}
  >
    <span className="aps-profit-icon" aria-hidden="true">{icon}</span>
    <span className="aps-profit-copy">
      <b>{busy ? "Controleren…" : label}</b>
      <strong>{profitMoney(bucket?.totalProfitUsd)}</strong>
      <small>{countLabel}</small>
      {note ? <em>{note}</em> : null}
    </span>
  </button>;
}

function HedgeSummary({ preview, onOpen }: { preview: ProfitPreview | null; onOpen: () => void }) {
  const exposure = preview?.exposure;
  const coverage = exposure?.reliable ? exposure.hedgeCoveragePercent : null;
  return <div className="aps-hedge-row" data-reference={REFERENCE}>
    <button
      type="button"
      className="aps-hedge-card"
      data-reference={HEDGE_CARD_REFERENCE}
      onClick={onOpen}
      aria-label={`Hedge dekking ${hedgePercent(coverage)}. Open details.`}
    >
      <span className="aps-hedge-shield"><Icon name="shield" /></span>
      <span className="aps-hedge-copy">
        <small>HEDGE DEKKING</small>
        <strong>{hedgePercent(coverage)}</strong>
      </span>
    </button>
    <div className="aps-exposure-strip" aria-label="Portfolio exposure">
      <article className="aps-exposure aps-exposure-long"><small>LONG EXPOSURE</small><strong>{exposure?.reliable ? exposureMoney(exposure.longExposureUsd) : "—"}</strong><span>LONG</span></article>
      <article className="aps-exposure aps-exposure-short"><small>SHORT EXPOSURE</small><strong>{exposure?.reliable ? exposureMoney(exposure.shortExposureUsd) : "—"}</strong><span>SHORT</span></article>
      <article className={`aps-exposure aps-exposure-net aps-net-${exposure?.netSide?.toLowerCase() || "flat"}`}><small>NETTO EXPOSURE</small><strong>{exposure?.reliable ? exposureMoney(exposure.netExposureUsd) : "—"}</strong><span>{exposure?.reliable ? netExposureLabel(exposure) : "—"}</span></article>
    </div>
  </div>;
}

function HedgeDetail({ preview, onClose }: { preview: ProfitPreview | null; onClose: () => void }) {
  const exposure = preview?.exposure;
  const config = preview?.hedgeConfig;
  const reliable = Boolean(exposure?.reliable && config);
  const coverage = reliable ? exposure?.hedgeCoveragePercent ?? null : null;
  const status = reliable ? exposure?.status ?? "unavailable" : "unavailable";
  const ringDegrees = Math.min(360, Math.max(0, (coverage ?? 0) * 3.6));
  const action = status === "within_target"
    ? "Je zit rond je doel. Nu niets doen."
    : status === "above_target"
      ? "Je hebt meer bescherming dan je doel. Winst op shorts kan ruimte geven om gecontroleerd af te bouwen."
      : status === "below_target"
        ? "Je hedge ligt onder je doel. Bij een verdere daling beweegt je portfoliowaarde sterker mee."
        : "De hedge-dekking kan nu niet betrouwbaar worden berekend.";
  return <div className="aps-sheet-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }} data-reference={HEDGE_DETAIL_REFERENCE}>
    <section className="aps-sheet aps-hedge-sheet" role="dialog" aria-modal="true" aria-labelledby="aps-hedge-title">
      <div className="aps-sheet-handle" />
      <button type="button" className="aps-sheet-x" onClick={onClose} aria-label="Sluiten">×</button>
      <header className="aps-sheet-title"><span className="aps-big-shield"><Icon name="shield" /></span><div><h3 id="aps-hedge-title">Hedge dekking</h3><p>Hoeveel van je longs nu beschermd worden door shorts</p></div></header>
      <div className="aps-hedge-overview">
        <div className="aps-coverage-ring" style={{ "--aps-coverage-angle": `${ringDegrees}deg` } as CSSProperties}>
          <div><strong>{hedgePercent(coverage)}</strong><b>{hedgeStatusLabel(status)}</b></div>
        </div>
        <div className="aps-hedge-target-card">
          <p>Doel <strong>{hedgePercent(config?.targetPercent)}</strong></p>
          <b>Gezonde zone: {hedgePercent(config?.healthyMinPercent)} – {hedgePercent(config?.healthyMaxPercent)}</b>
          <span>{reliable ? `Je hedge dekking is ${hedgePercent(coverage)}. ${status === "within_target" ? "Dit ligt binnen de doelzone." : status === "above_target" ? "Dit ligt boven je doelzone." : "Dit ligt onder je doelzone."}` : "Live exposure is tijdelijk niet betrouwbaar beschikbaar."}</span>
        </div>
      </div>
      <div className="aps-detail-exposures">
        <article className="long"><small>LONG EXPOSURE</small><strong>{reliable ? exposureMoney(exposure?.longExposureUsd) : "—"}</strong><span>LONG</span></article>
        <article className="short"><small>SHORT EXPOSURE</small><strong>{reliable ? exposureMoney(exposure?.shortExposureUsd) : "—"}</strong><span>SHORT</span></article>
        <article className="net"><small>NETTO OPEN</small><strong>{reliable ? exposureMoney(exposure?.netExposureUsd, true) : "—"}</strong><span>{reliable ? netExposureLabel(exposure) : "—"}</span></article>
      </div>
      <div className="aps-explain">
        <h4>Wat betekent dit?</h4>
        <p><span>🛡</span> Shorts beschermen je longs</p>
        <p><span>▥</span> Meer dekking = minder schommeling</p>
        <p><span>↗</span> Minder dekking = meer kans op winst, maar ook meer risico</p>
      </div>
      <div className={`aps-action-now aps-action-${status}`}><h4>Actie nu</h4><p><Icon name="shield" /><strong>{action}</strong></p></div>
      <button type="button" className="aps-sheet-close" onClick={onClose}>Sluiten</button>
    </section>
  </div>;
}

function CloseImpactSheet({ scope, bucket, config, busy, onCancel, onConfirm }: {
  scope: ProfitScope;
  bucket: ProfitBucket;
  config: HedgeConfig;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const impact = bucket.impact;
  const reliable = impact.before.reliable && impact.after.reliable;
  const towardTarget = reliable && impact.impactType === "toward_target";
  const protectionFalls = reliable && impact.protectionDirection === "decreases";
  const protectionRises = reliable && impact.protectionDirection === "increases";
  const riskyShort = scope === "SHORT" && protectionFalls && !towardTarget;
  const awayFromTarget = reliable && impact.impactType === "away_from_target";
  const positive = towardTarget;
  const caution = !positive && (riskyShort || awayFromTarget || protectionRises);
  const mode = positive ? "positive" : caution ? "warning" : "neutral";
  const countLabel = `${bucket.eligibleCount} ${bucket.eligibleCount === 1 ? "positie" : "posities"}`;
  const title = scope === "LONG" ? "Close Long" : scope === "SHORT" ? "Close Short" : "Close All";
  const beforeCoverage = reliable ? hedgePercent(impact.before.hedgeCoveragePercent) : "—";
  const afterCoverage = reliable ? hedgePercent(impact.after.hedgeCoveragePercent) : "—";
  const beforeStatus = reliable ? hedgeStatusLabel(impact.before.status) : "—";
  const afterStatus = reliable ? hedgeStatusLabel(impact.after.status) : "—";
  const reference = positive ? CLOSE_POSITIVE_REFERENCE : CLOSE_RISK_REFERENCE;

  let headline = "Bekijk wat deze sluiting met je bescherming doet.";
  let subline = "Je houdt zelf de beslissing.";
  if (!reliable) {
    headline = "De hedge-impact kan nu niet volledig betrouwbaar worden berekend.";
    subline = "De winstselectie is wel opnieuw gecontroleerd. Sluit alleen als je de gevolgen zelf accepteert.";
  } else if (positive) {
    headline = "Deze sluiting brengt je hedge richting je doel.";
    subline = "Je pakt winst en brengt je bescherming dichter bij de ingestelde verhouding.";
  } else if (riskyShort) {
    headline = "Je sluit winst, maar je haalt ook bescherming weg.";
    subline = "Bij verdere daling kan je portfoliowaarde harder dalen.";
  } else if (protectionRises && awayFromTarget) {
    headline = "Deze sluiting maakt je portefeuille zwaarder gehedged.";
    subline = "Je bescherming stijgt, maar je beweegt verder weg van je hedge-doel.";
  } else if (awayFromTarget) {
    headline = "Deze sluiting beweegt je hedge weg van je doel.";
    subline = "Controleer de verhouding voordat je doorgaat.";
  }

  const confirmLabel = busy ? "Sluiten…" : positive
    ? scope === "SHORT" ? `Sluit ${bucket.eligibleCount} ${bucket.eligibleCount === 1 ? "short" : "shorts"}` : "Sluiten"
    : riskyShort ? "Toch sluiten" : "Sluiten";

  return <div className="aps-sheet-backdrop" role="presentation" onMouseDown={(event) => { if (!busy && event.target === event.currentTarget) onCancel(); }} data-reference={reference}>
    <section className={`aps-sheet aps-close-sheet aps-close-${mode}`} role="dialog" aria-modal="true" aria-labelledby="aps-close-title">
      <div className="aps-sheet-handle" />
      <button type="button" className="aps-sheet-x" onClick={onCancel} disabled={busy} aria-label="Sluiten">×</button>
      <header className="aps-close-heading"><span className={`aps-close-direction scope-${scope.toLowerCase()}`}>{scope === "LONG" ? "↗" : scope === "SHORT" ? "↘" : "◎"}</span><h3 id="aps-close-title">{title}</h3></header>
      <div className="aps-close-profit"><span>$</span><div><strong>{profitMoney(bucket.totalProfitUsd)}</strong><small>{countLabel}</small></div></div>
      <div className={`aps-close-message aps-message-${mode}`}><span>{positive ? "✓" : mode === "warning" ? "!" : "i"}</span><div><strong>{headline}</strong><p>{subline}</p></div></div>

      <div className="aps-before-after">
        <div className="aps-ba-head"><span /><small>NU</small><small>NA SLUITEN</small></div>
        <div className="aps-ba-row"><b>Hedge dekking<small>Bescherming van je portfolio</small></b><strong>{beforeCoverage}</strong><i>→</i><strong>{afterCoverage}</strong></div>
        <div className="aps-ba-row"><b>Netto open<small>Marktexposure (US$)</small></b><strong>{reliable ? exposureMoney(impact.before.netExposureUsd, true) : "—"}<small>{reliable ? netExposureLabel(impact.before) : ""}</small></strong><i>→</i><strong>{reliable ? exposureMoney(impact.after.netExposureUsd, true) : "—"}<small>{reliable ? netExposureLabel(impact.after) : ""}</small></strong></div>
        <div className="aps-ba-row"><b>Status<small>Doel {hedgePercent(config.targetPercent)}</small></b><strong>{beforeStatus}</strong><i>→</i><strong>{afterStatus}</strong></div>
      </div>

      {scope === "SHORT" && reliable ? <div className="aps-removed-exposure"><span>SHORT exposure die je sluit</span><strong>{exposureMoney(impact.removedShortExposureUsd)}</strong></div> : null}
      {scope === "LONG" && reliable ? <div className="aps-removed-exposure"><span>LONG exposure die je sluit</span><strong>{exposureMoney(impact.removedLongExposureUsd)}</strong></div> : null}
      {scope === "ALL" && reliable ? <div className="aps-removed-exposure"><span>Exposure die je sluit</span><strong>L {exposureMoney(impact.removedLongExposureUsd)} · S {exposureMoney(impact.removedShortExposureUsd)}</strong></div> : null}

      {positive ? <div className="aps-close-reason"><h4>Waarom past dit nu?</h4><p>✓ Je beweegt richting je hedge-doel</p><p>✓ De nieuwe verhouding is gunstiger ten opzichte van je ingestelde doel</p></div> : null}
      {riskyShort ? <div className="aps-close-advice">Advies: nu liever niet sluiten als je deze shorts als hedge nodig hebt.</div> : null}
      {!reliable ? <div className="aps-close-advice">Geen risico-percentages verzonnen: onbetrouwbare hedge-data wordt bewust niet ingevuld.</div> : null}

      <div className="aps-close-buttons">
        <button type="button" className="aps-cancel" onClick={onCancel} disabled={busy}>Annuleren<small>{riskyShort ? "Houd je bescherming aan" : "Niets wijzigen"}</small></button>
        <button type="button" className={`aps-confirm aps-confirm-${mode}`} onClick={onConfirm} disabled={busy}>{confirmLabel}<small>{riskyShort ? "Neem winst en verlaag hedge" : positive ? "Pak winst en herstel verhouding" : "Voer sluiting uit"}</small></button>
      </div>
    </section>
  </div>;
}

function PriceZoneStrategySummary({ summary, liveActiveZone }: { summary: PriceZoneSeatSummary | null; liveActiveZone: number | null }) {
  const liveZoneLabel = liveActiveZone === null ? "—" : `Zone ${liveActiveZone} actief`;
  if (!summary) return <section className="aps-zone-strategy aps-zone-loading" data-reference={PRICE_ZONE_DETAILS_REFERENCE} data-seat-zone-sync="waiting"><div className="aps-zone-title"><span className="aps-zone-target">◎</span><div><b>Prijszone-strategie</b><small>Live stoelstatus wordt geladen…</small></div><em>{liveZoneLabel}</em></div></section>;
  const pct = (value: number, capacity: number) => capacity <= 0 ? 0 : Math.min(100, Math.max(0, value / capacity * 100));
  const displayActiveZone = summary.runtimeTruthCanonical ? summary.activeZone : (liveActiveZone ?? summary.activeZone);
  const backendZoneMatches = displayActiveZone !== null && summary.activeZone === displayActiveZone;
  const breakdown = displayActiveZone === null ? null : summary.zoneOpenCounts[String(displayActiveZone)] || null;
  const resolvedCounts = backendZoneMatches
    ? { long: summary.occupiedLongActiveZone, short: summary.occupiedShortActiveZone }
    : displayActiveZone !== null && summary.zoneOpenCountsReliable
      ? { long: breakdown?.long ?? 0, short: breakdown?.short ?? 0 }
      : null;
  const seatZoneInSync = resolvedCounts !== null;
  const zoneLabel = displayActiveZone === null ? "Zone —" : `Zone ${displayActiveZone} actief`;
  const occupiedLongActiveZone = resolvedCounts?.long ?? 0;
  const occupiedShortActiveZone = resolvedCounts?.short ?? 0;
  const freeLongActiveZone = Math.max(0, summary.perZoneLong - occupiedLongActiveZone);
  const freeShortActiveZone = Math.max(0, summary.perZoneShort - occupiedShortActiveZone);
  const activeLongLabel = seatZoneInSync ? `${occupiedLongActiveZone} / ${summary.perZoneLong}` : "— / —";
  const activeShortLabel = seatZoneInSync ? `${occupiedShortActiveZone} / ${summary.perZoneShort}` : "— / —";
  const statusText = !summary.enabled
    ? "Prijszone-stoelen staan momenteel uit."
    : seatZoneInSync
      ? "Alleen vrije stoelen in de actieve prijszone worden gevuld."
      : "Live zone gewijzigd · stoelstatus synchroniseert.";
  const blockerText = summary.dynamicHedgeBlocking
    ? `Instap geblokkeerd · Dynamic Hedge · ${summary.dynamicHedgeReason || summary.dynamicHedgeOwnershipState || "wacht op veilige state"}${summary.dynamicHedgeSafetyStatus ? ` · ${summary.dynamicHedgeSafetyStatus}` : ""}`
    : summary.queueHaltedUncertain
      ? `Instap geblokkeerd · orderreconciliatie · ${summary.queueUncertainReason || "onzekere Aster-order"}`
      : summary.zoneMigrationHold
        ? "Instap wacht · zone-migratie wordt één tick gereconcilieerd"
        : summary.entryStatus
          ? `Instapstatus · ${summary.entryStatus}${summary.entryReason ? ` · ${summary.entryReason}` : ""}`
          : "Instapstatus · wacht op nieuwe scanner-evaluatie";
  return <section className={"aps-zone-strategy " + (summary.enabled ? "is-active" : "is-off")} data-reference={PRICE_ZONE_DETAILS_REFERENCE} data-seat-zone-sync={seatZoneInSync ? "synced" : "waiting"}>
    <div className="aps-zone-title">
      <span className="aps-zone-target" aria-hidden="true">◎</span>
      <div><b>Prijszone-strategie</b><small>{statusText}</small></div>
      <em>{summary.enabled ? zoneLabel : "UIT"}</em>
    </div>
    <div className="aps-zone-facts">
      <span><small>Per zone</small><b>{summary.perZoneLong}L / {summary.perZoneShort}S</b></span>
      <span><small>Vrij in actieve zone</small>{seatZoneInSync ? <b><i>{freeLongActiveZone}L</i> / <em>{freeShortActiveZone}S</em></b> : <b>— / —</b>}</span>
      <span><small>Oude zones open</small><b>{summary.openFromOldZones}</b></span>
      <span><small>Max totaal</small><b>{summary.maxTotal}</b></span>
    </div>
    <div className="aps-zone-seat-groups">
      <div className="aps-zone-seat-group">
        <strong className="aps-zone-group-title">Actieve zone</strong>
        <div className="aps-zone-meters">
          <div className="long"><span>LONG</span><i><u style={{width:`${seatZoneInSync ? pct(occupiedLongActiveZone,summary.perZoneLong) : 0}%`}} /></i><b>{activeLongLabel}</b></div>
          <div className="short"><span>SHORT</span><i><u style={{width:`${seatZoneInSync ? pct(occupiedShortActiveZone,summary.perZoneShort) : 0}%`}} /></i><b>{activeShortLabel}</b></div>
        </div>
      </div>
      <div className="aps-zone-seat-group">
        <strong className="aps-zone-group-title">Alle zones samen</strong>
        <div className="aps-zone-open-counts">
          <div className="long"><span>LONG totaal open</span><b>{summary.strategyOpenLong}</b></div>
          <div className="short"><span>SHORT totaal open</span><b>{summary.strategyOpenShort}</b></div>
        </div>
        <div className="aps-zone-meters aps-zone-total-meter">
          <div className="total"><span>Totaal bezet</span><i><u style={{width:`${pct(summary.strategyOpenTotal,summary.maxTotal)}%`}} /></i><b>{summary.strategyOpenTotal} / {summary.maxTotal}</b></div>
        </div>
      </div>
    </div>
    <p><span aria-hidden="true">ⓘ</span>{blockerText}</p>
    <p><span aria-hidden="true">ⓘ</span>Bestaande posities houden hun zone-stoel bezet. Bij terugkeer worden alleen lege stoelen gevuld.</p>
  </section>;
}

function SnapshotDetailButtons({ onOpenPriceZone, onOpenScanner }: {
  onOpenPriceZone: () => void;
  onOpenScanner: () => void;
}) {
  return <div className="aps-detail-actions" data-reference={SNAPSHOT_DETAIL_BUTTONS_REFERENCE} aria-label="Portfolio detailweergaven">
    <button type="button" className="aps-detail-action aps-detail-action-zone" onClick={onOpenPriceZone} aria-label="Prijszone Details openen">
      <span className="aps-detail-action-icon" aria-hidden="true">◎</span>
      <span><b>Prijszone Details</b><small>Dubbelklik · 3D flip</small></span>
      <em aria-hidden="true">›</em>
    </button>
    <button type="button" className="aps-detail-action aps-detail-action-scanner" onClick={onOpenScanner} aria-label="Scanner Status openen">
      <span className="aps-detail-action-icon" aria-hidden="true">⌁</span>
      <span><b>Scanner Status</b><small>Dubbelklik · 3D flip</small></span>
      <em aria-hidden="true">›</em>
    </button>
  </div>;
}

function formatScannerClock(timestampMs: number | null) {
  if (!timestampMs || !Number.isFinite(timestampMs)) return "—";
  return new Intl.DateTimeFormat("nl-NL", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(timestampMs));
}

function formatScannerAge(timestampMs: number | null) {
  if (!timestampMs || !Number.isFinite(timestampMs)) return "—";
  const seconds = Math.max(0, Math.floor((Date.now() - timestampMs) / 1000));
  if (seconds < 60) return seconds + " sec geleden";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return minutes + " min geleden";
  const hours = Math.floor(minutes / 60);
  return hours + "u " + (minutes % 60) + "m geleden";
}

function scannerVerdict(snapshot: ScannerStatusSnapshot | null): ScannerVerdict {
  if (!snapshot?.updatedAtMs || Date.now() - snapshot.updatedAtMs > 120000) return "SCANNER STIL";
  if (!snapshot.enabled) return "GEBLOKKEERD";
  if (snapshot.entryStatus === "ORDER_REJECTED") return "ORDERFOUT";
  const sides = [snapshot.long, snapshot.short];
  const hasRuntimeCounters = sides.some((side) => side.bbCandidates !== null || side.marketsScanned !== null);
  if (!hasRuntimeCounters) return "GEBLOKKEERD";
  const freeCapacity = sides.reduce((sum, side) => sum + (side.availableCapacity ?? 0), 0);
  const bbCandidates = sides.reduce((sum, side) => sum + (side.bbCandidates ?? 0), 0);
  const blockers = sides.reduce((sum, side) => sum + (side.blockedFilters ?? 0), snapshot.unscopedBlocked ?? 0);
  const orders = sides.reduce((sum, side) => sum + (side.ordersPlaced ?? 0), 0);
  if (freeCapacity > 0 && bbCandidates === 0) return "GEEN KANDIDATEN";
  if (freeCapacity > 0 && bbCandidates > 0 && orders === 0 && blockers > 0) return "GEBLOKKEERD";
  return "NORMAAL";
}

function scannerConclusion(snapshot: ScannerStatusSnapshot | null, verdict: ScannerVerdict) {
  if (!snapshot) return "Live scannerdiagnostiek wordt geladen.";
  if (verdict === "SCANNER STIL") return "De laatste scanner-heartbeat is ouder dan twee minuten. Controleer de runtime voordat nieuwe entries worden verwacht.";
  if (verdict === "ORDERFOUT") return snapshot.entryReason || "De scanner vond een entry, maar de ordercontrole heeft deze afgewezen.";
  if (verdict === "GEBLOKKEERD" && snapshot.long.marketsScanned === null && snapshot.short.marketsScanned === null) {
    return "De scanner draait, maar de nieuwe read-only diagnosevelden zijn nog niet beschikbaar in deze runtime.";
  }
  const describe = (label: string, side: ScannerSideStatus) => {
    if ((side.availableCapacity ?? 0) <= 0) return label + ": geen vrije stoel.";
    if (side.bbCandidates === 0) return label + ": geen geldige Bollinger-kandidaat in de laatste scan; " + (side.availableCapacity ?? 0) + " stoel(en) vrij.";
    if ((side.ordersPlaced ?? 0) > 0) return label + ": " + (side.bbCandidates ?? 0) + " kandidaat/kandidaten; " + (side.ordersPlaced ?? 0) + " order(s) geplaatst.";
    if ((side.blockedFilters ?? 0) > 0) return label + ": " + (side.bbCandidates ?? 0) + " kandidaat/kandidaten; " + (side.blockedFilters ?? 0) + " geblokkeerd na de entryfilter.";
    return label + ": " + (side.bbCandidates ?? 0) + " kandidaat/kandidaten; geen order geplaatst in de laatste scan.";
  };
  return describe("LONG", snapshot.long) + " " + describe("SHORT", snapshot.short);
}

function PriceZoneDetailsPage({ summary, liveActiveZone, onBack }: {
  summary: PriceZoneSeatSummary | null;
  liveActiveZone: number | null;
  onBack: () => void;
}) {
  return <section className="aps-detail-page aps-price-zone-page" data-reference={PRICE_ZONE_DETAILS_REFERENCE} aria-label="Prijszone Details">
    <button type="button" className="aps-detail-back" onClick={onBack}><span aria-hidden="true">←</span><b>Dubbelklik om terug te gaan</b></button>
    <div className="aps-detail-page-title">
      <span className="aps-detail-page-icon" aria-hidden="true">◎</span>
      <div><h2>Prijszone details</h2><p>Gedetailleerde live weergave van de prijszone-strategie</p></div>
    </div>
    <PriceZoneStrategySummary summary={summary} liveActiveZone={liveActiveZone} />
  </section>;
}

function ScannerSidePanel({ side, data, updatedAtMs, active }: {
  side: "LONG" | "SHORT";
  data: ScannerSideStatus;
  updatedAtMs: number | null;
  active: boolean;
}) {
  const value = (number: number | null) => number === null ? "—" : String(number);
  return <article className={"aps-scanner-side aps-scanner-" + side.toLowerCase()}>
    <header><div><span aria-hidden="true">{side === "LONG" ? "↗" : "↘"}</span><h3>{side} <small>({data.timeframe})</small></h3></div><em className={active ? "is-active" : "is-inactive"}>{active ? "ACTIEF" : "INACTIEF"}</em></header>
    <dl>
      <div><dt>Laatste scan</dt><dd>{formatScannerClock(updatedAtMs)} <small>{formatScannerAge(updatedAtMs)}</small></dd></div>
      <div><dt>Markten gescand</dt><dd>{value(data.marketsScanned)}</dd></div>
      <div><dt>BB-kandidaten</dt><dd>{value(data.bbCandidates)}</dd></div>
      <div><dt>Zone toegestaan</dt><dd>{value(data.zoneAllowed)}</dd></div>
      <div><dt>Geblokkeerd (filters)</dt><dd>{value(data.blockedFilters)}</dd></div>
      <div><dt>Orders geplaatst</dt><dd>{value(data.ordersPlaced)}</dd></div>
      <div><dt>Laatste entry</dt><dd>{formatScannerClock(data.lastEntryAtMs)} <small>{formatScannerAge(data.lastEntryAtMs)}</small></dd></div>
      <div><dt>Heartbeat</dt><dd className="is-live">{formatScannerClock(updatedAtMs)}</dd></div>
      <div><dt>Vrije stoelen</dt><dd>{value(data.availableCapacity)}</dd></div>
    </dl>
  </article>;
}

function ScannerStatusPage({ snapshot, onBack }: { snapshot: ScannerStatusSnapshot | null; onBack: () => void }) {
  const verdict = scannerVerdict(snapshot);
  const fresh = Boolean(snapshot?.updatedAtMs && Date.now() - snapshot.updatedAtMs <= 120000);
  return <section className="aps-detail-page aps-scanner-page" data-reference={SCANNER_STATUS_REFERENCE} aria-label="Scanner Status">
    <button type="button" className="aps-detail-back" onClick={onBack}><span aria-hidden="true">←</span><b>Dubbelklik om terug te gaan</b></button>
    <div className="aps-detail-page-title aps-scanner-title">
      <span className="aps-detail-page-icon" aria-hidden="true">⌁</span>
      <div><h2>Scanner Status</h2><p>Live read-only analyse van entrycondities en marktfilters</p></div>
      <em className={fresh ? "is-live" : "is-stale"}><i />{fresh ? "Live" : "Stil"}</em>
    </div>
    <div className={"aps-entry-health aps-entry-health-" + verdict.toLowerCase().replaceAll(" ", "-")}>
      <div><small>ENTRY HEALTH</small><strong>{verdict}</strong><p>{snapshot?.entryReason || "Wacht op de volgende scanner-evaluatie."}</p></div>
      <ul>
        <li><i className={fresh ? "ok" : "bad"} />Scanner {fresh ? "actief" : "geen recente heartbeat"}</li>
        <li><i className={snapshot?.enabled ? "ok" : "bad"} />Strategie {snapshot?.enabled ? "actief" : "uit"}</li>
        <li><i className={snapshot?.long.timeframe !== "—" && snapshot?.short.timeframe !== "—" ? "ok" : "bad"} />Timeframes uit runtime</li>
      </ul>
    </div>
    <div className="aps-scanner-grid">
      <ScannerSidePanel side="LONG" data={snapshot?.long ?? scannerSideStatus({})} updatedAtMs={snapshot?.updatedAtMs ?? null} active={fresh && snapshot?.enabled === true} />
      <ScannerSidePanel side="SHORT" data={snapshot?.short ?? scannerSideStatus({})} updatedAtMs={snapshot?.updatedAtMs ?? null} active={fresh && snapshot?.enabled === true} />
    </div>
    <div className="aps-scanner-conclusion"><span aria-hidden="true">ⓘ</span><div><b>CONCLUSIE</b><p>{scannerConclusion(snapshot, verdict)}</p></div></div>
  </section>;
}

function Snapshot({ values, profitPreview, liquidationDiagnostics, profitBusy, onCloseAll, onCloseProfit, onOpenHedge, onOpenPriceZone, onOpenScanner, onOpenPerformance }: {
  values: SnapshotValues;
  profitPreview: ProfitPreview | null;
  liquidationDiagnostics: LiquidationDiagnostics | null;
  profitBusy: ProfitScope | null;
  onCloseAll: () => void;
  onCloseProfit: (scope: ProfitScope) => void;
  onOpenHedge: () => void;
  onOpenPriceZone: () => void;
  onOpenScanner: () => void;
  onOpenPerformance: (tab: PerformanceInitialTab) => void;
}) {
  return <section className="aster-portfolio-snapshot" aria-label="Portfolio Snapshot" data-reference={SNAPSHOT_V2_REFERENCE}>
    <header>
      <div className="aps-title-icon"><Icon name="positions" /></div>
      <h2>PORTFOLIO SNAPSHOT</h2>
      <div className="aps-header-actions">
        <span className="aps-live"><i />Live</span>
        <button type="button" className="aps-close-all" disabled={values.closeDisabled} onClick={onCloseAll}>{values.closeBusy ? "SLUITEN…" : "ALLES SLUITEN"}</button>
      </div>
    </header>
    <SnapshotDetailButtons onOpenPriceZone={onOpenPriceZone} onOpenScanner={onOpenScanner} />
    <div className="aps-grid">
      <MetricCard icon="wallet" label="PORTFOLIOWAARDE" value={values.equity} detail={values.todayGrowth !== "—" ? `${values.todayGrowth} vandaag` : undefined} detailTone={values.todayGrowthTone === "positive" ? "positive" : values.todayGrowthTone === "negative" ? "negative" : "muted"} />
      <MetricCard icon="coins" label="AVAILABLE TO TRADE" value={values.available} />
      <MetricCard icon="capital" label="ACTIEF TRADE CAPITAL" value={values.activeCapital} />
      <MetricCard icon="positions" label="ACTIEVE POSITIES" value={values.activePositions} detail={values.longs !== "—" && values.shorts !== "—" ? `${values.longs} Long  ${values.shorts} Short` : undefined} />
      <MetricCard icon="result" label="GESLOTEN RESULTAAT" value={values.realized} tone={values.realizedTone === "positive" ? "positive" : values.realizedTone === "negative" ? "negative" : "normal"} detail="Vandaag" detailTone={values.realizedTone === "positive" ? "positive" : values.realizedTone === "negative" ? "negative" : "muted"} />
      <MetricCard icon="trades" label="TRADES GESLOTEN" value={values.tradesClosed} detail="Vandaag" />
    </div>
    <HedgeSummary preview={profitPreview} onOpen={onOpenHedge} />
    <div className="aps-health-grid">
      <div className="aps-health-left">
        <div className="aps-status-row">
          <div className="aps-status aps-balance"><Icon name="balance" /><strong><b>{values.longCapacity !== "—" ? `${values.longs}/${values.longCapacity}L` : `${values.longs}L`}</b><span>/</span><em>{values.shortCapacity !== "—" ? `${values.shorts}/${values.shortCapacity}S` : `${values.shorts}S`}</em></strong></div>
          <div className="aps-status"><Icon name="dca" /><strong>{values.dca} DCA</strong></div>
        </div>
        <div className="aps-growth-row">
          <GrowthCard icon="growth" label="RENDEMENT VANDAAG" value={values.todayGrowth} tone={values.todayGrowthTone} detail="excl. stortingen & opnames" onClick={() => onOpenPerformance("per-day")} />
          <GrowthCard icon="calendar" label="GEMIDDELD PER DAG" value={values.averageDailyGrowth} tone={values.averageDailyGrowthTone} onClick={() => onOpenPerformance("average")} />
        </div>
      </div>
      <LiquidationGauge
        value={values.liquidation}
        diagnostics={liquidationDiagnostics}
        exposure={profitPreview?.exposure}
        equity={values.equity}
        available={values.available}
      />
    </div>
    <div className="aps-profit-row" aria-label="Winstposities sluiten">
      <ProfitAction scope="LONG" label="Close Long" bucket={profitPreview?.long ?? null} busy={profitBusy === "LONG"} onClick={onCloseProfit} />
      <ProfitAction scope="SHORT" label="Close Short" bucket={profitPreview?.short ?? null} busy={profitBusy === "SHORT"} onClick={onCloseProfit} />
      <ProfitAction scope="ALL" label="Close All" bucket={profitPreview?.all ?? null} busy={profitBusy === "ALL"} onClick={onCloseProfit} />
    </div>
  </section>;
}

function finiteExposure(exposure: ExposureSnapshot | undefined) {
  return Boolean(exposure
    && typeof exposure.reliable === "boolean"
    && Number.isFinite(exposure.longExposureUsd)
    && Number.isFinite(exposure.shortExposureUsd)
    && Number.isFinite(exposure.netExposureUsd));
}

async function loadProfitPreview(): Promise<ProfitPreview> {
  const payload = await authenticatedRequest("/api/exchanges/aster/positions/profitable-close-preview", { cache: "no-store" }) as ProfitPreview;
  const buckets = [payload?.long, payload?.short, payload?.all];
  const validConfig = payload?.hedgeConfig
    && Number.isFinite(payload.hedgeConfig.targetPercent)
    && Number.isFinite(payload.hedgeConfig.healthyMinPercent)
    && Number.isFinite(payload.hedgeConfig.healthyMaxPercent);
  const valid = payload?.reliable === true
    && payload?.comparison === "greater_than_or_equal"
    && validConfig
    && finiteExposure(payload?.exposure)
    && buckets.every((bucket) => bucket
      && Number.isInteger(bucket.eligibleCount)
      && bucket.eligibleCount >= 0
      && Number.isFinite(bucket.totalProfitUsd)
      && bucket.impact
      && finiteExposure(bucket.impact.before)
      && finiteExposure(bucket.impact.after));
  if (!valid) throw new Error("De actuele winst- en hedgecontrole is niet betrouwbaar beschikbaar.");
  return payload;
}

export function AsterPortfolioSnapshotEnhancer() {
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [values, setValues] = useState<SnapshotValues>(EMPTY);
  const [profitPreview, setProfitPreview] = useState<ProfitPreview | null>(null);
  const [liquidationDiagnostics, setLiquidationDiagnostics] = useState<LiquidationDiagnostics | null>(null);
  const [profitBusy, setProfitBusy] = useState<ProfitScope | null>(null);
  const [priceZoneSeats, setPriceZoneSeats] = useState<PriceZoneSeatSummary | null>(null);
  const [scannerStatus, setScannerStatus] = useState<ScannerStatusSnapshot | null>(null);
  const [liveActiveZone, setLiveActiveZone] = useState<number | null>(null);
  const [detailView, setDetailView] = useState<SnapshotDetailView>("portfolio");
  const [performanceInitialTab, setPerformanceInitialTab] = useState<PerformanceInitialTab>("per-day");
  const [hedgeOpen, setHedgeOpen] = useState(false);
  const [confirmScope, setConfirmScope] = useState<ProfitScope | null>(null);
  const valuesRef = useRef<SnapshotValues>(EMPTY);
  const detailScrollY = useRef(0);
  const syncing = useRef(false);

  useEffect(() => {
    let observer: MutationObserver | null = null;
    let frame = 0;
    let alive = true;
    const sync = () => {
      if (!alive || syncing.current) return;
      syncing.current = true;
      frame = window.requestAnimationFrame(() => {
        syncing.current = false;
        const asterHero = document.querySelector(".aster-liquidation-hero");
        const impact = document.querySelector<HTMLElement>('section[aria-label^="Portfolio impact."]');
        const active = Boolean(asterHero && impact);
        if (!active) {
          document.documentElement.removeAttribute("data-aster-compact-snapshot");
          setHost((current) => current === null ? current : null);
          return;
        }
        document.documentElement.setAttribute("data-aster-compact-snapshot", "true");
        let mount = document.getElementById("aster-portfolio-snapshot-host");
        if (!mount) {
          mount = document.createElement("div");
          mount.id = "aster-portfolio-snapshot-host";
        }
        const battleRoot = impact.parentElement;
        if (battleRoot?.parentElement && (mount.parentElement !== battleRoot.parentElement || mount.nextElementSibling !== battleRoot)) battleRoot.parentElement.insertBefore(mount, battleRoot);
        setHost((current) => current === mount ? current : mount);
        const next = readSnapshot();
        if (!valuesEqual(valuesRef.current, next)) {
          valuesRef.current = next;
          setValues(next);
        }
      });
    };
    observer = new MutationObserver(sync);
    observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["class", "disabled"] });
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    sync();
    const timer = window.setInterval(sync, 5000);
    return () => {
      alive = false;
      observer?.disconnect();
      window.clearInterval(timer);
      window.cancelAnimationFrame(frame);
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
      document.documentElement.removeAttribute("data-aster-compact-snapshot");
      document.getElementById("aster-portfolio-snapshot-host")?.remove();
    };
  }, []);

  useEffect(() => {
    if (!host) return;
    let alive = true;
    const refresh = async () => {
      try {
        const preview = await loadProfitPreview();
        if (alive) setProfitPreview(preview);
      } catch {
        if (alive) setProfitPreview(null);
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 15000);
    const onVisible = () => { if (document.visibilityState === "visible") void refresh(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [host]);

  useEffect(() => {
    if (!host) return;
    let alive = true;
    const refresh = async () => {
      try {
        const diagnostics = await loadLiquidationDiagnostics();
        if (alive) setLiquidationDiagnostics(diagnostics);
      } catch {
        if (alive) setLiquidationDiagnostics(null);
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 15000);
    const onVisible = () => { if (document.visibilityState === "visible") void refresh(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [host]);

  useEffect(() => {
    if (!host) return;
    let alive = true;
    const refresh = async () => {
      try {
        const summary = await loadPriceZoneSeatSummary();
        if (alive) setPriceZoneSeats(summary);
      } catch {
        if (alive) setPriceZoneSeats(null);
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 15000);
    const onVisible = () => { if (document.visibilityState === "visible") void refresh(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [host, liveActiveZone]);

  useEffect(() => {
    if (!host) return;
    let alive = true;
    const refresh = async () => {
      try {
        const status = await loadScannerStatus();
        if (alive) setScannerStatus(status);
      } catch {
        if (alive) setScannerStatus(null);
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 5000);
    const onVisible = () => { if (document.visibilityState === "visible") void refresh(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [host]);

  useEffect(() => {
    const modalOpen = hedgeOpen || Boolean(confirmScope);
    if (!modalOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !profitBusy) {
        setHedgeOpen(false);
        setConfirmScope(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
    };
  }, [hedgeOpen, confirmScope, profitBusy]);

  const closeAll = () => {
    const legacy = document.querySelector<HTMLButtonElement>(".portfolio-close-all");
    if (!legacy || legacy.disabled) return;
    legacy.click();
  };

  const openProfitPreview = async (scope: ProfitScope) => {
    if (profitBusy) return;
    setProfitBusy(scope);
    try {
      const fresh = await loadProfitPreview();
      setProfitPreview(fresh);
      const bucket = scope === "LONG" ? fresh.long : scope === "SHORT" ? fresh.short : fresh.all;
      if (bucket.eligibleCount < 1) return;
      setConfirmScope(scope);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "De winst- en hedgecontrole kon niet veilig worden geladen.");
    } finally {
      setProfitBusy(null);
    }
  };

  const confirmProfitClose = async () => {
    const scope = confirmScope;
    if (!scope || profitBusy) return;
    setProfitBusy(scope);
    try {
      const fresh = await loadProfitPreview();
      setProfitPreview(fresh);
      const bucket = scope === "LONG" ? fresh.long : scope === "SHORT" ? fresh.short : fresh.all;
      if (bucket.eligibleCount < 1) {
        setConfirmScope(null);
        return;
      }
      await authenticatedRequest(`/api/exchanges/aster/positions/close-profitable?side=${scope}`, {
        method: "POST",
        body: JSON.stringify({
          confirm: true,
          idempotency_key: `snapshot-profit-${scope.toLowerCase()}-${Date.now()}-${crypto.randomUUID()}`,
        }),
      });
      setConfirmScope(null);
      window.setTimeout(async () => {
        try { setProfitPreview(await loadProfitPreview()); } catch { setProfitPreview(null); }
      }, 600);
      window.setTimeout(async () => {
        try { setProfitPreview(await loadProfitPreview()); } catch { /* keep last reliable values */ }
      }, 2400);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "De winstposities konden niet veilig worden gesloten.");
    } finally {
      setProfitBusy(null);
    }
  };

  const openDetail = (next: Exclude<SnapshotDetailView, "portfolio">) => {
    detailScrollY.current = window.scrollY;
    setDetailView(next);
    window.requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: "auto" }));
  };

  const openPerformance = (tab: PerformanceInitialTab) => {
    setPerformanceInitialTab(tab);
    openDetail("performance");
  };

  const closeDetail = () => {
    const restoreY = detailScrollY.current;
    setDetailView("portfolio");
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => window.scrollTo({ top: restoreY, behavior: "auto" }));
    });
  };

  const confirmBucket = confirmScope && profitPreview
    ? confirmScope === "LONG" ? profitPreview.long : confirmScope === "SHORT" ? profitPreview.short : profitPreview.all
    : null;

  return host ? createPortal(
    <>
      {detailView === "portfolio" ? <>
        <PortfolioKoersChart
          liveEquityText={values.equity}
          liveAvailableText={values.available}
          liveLongText={values.longs}
          liveShortText={values.shorts}
          onActiveZoneChange={setLiveActiveZone}
        />
        <Snapshot
          values={values}
          profitPreview={profitPreview}
          liquidationDiagnostics={liquidationDiagnostics}
          profitBusy={profitBusy}
          onCloseAll={closeAll}
          onCloseProfit={openProfitPreview}
          onOpenHedge={() => setHedgeOpen(true)}
          onOpenPriceZone={() => openDetail("price-zone")}
          onOpenScanner={() => openDetail("scanner")}
          onOpenPerformance={openPerformance}
        />
        {hedgeOpen ? <AsterHedgeManager onClose={() => setHedgeOpen(false)} /> : null}
        {confirmScope && confirmBucket && profitPreview ? <CloseImpactSheet
          scope={confirmScope}
          bucket={confirmBucket}
          config={profitPreview.hedgeConfig}
          busy={profitBusy === confirmScope}
          onCancel={() => { if (!profitBusy) setConfirmScope(null); }}
          onConfirm={confirmProfitClose}
        /> : null}
      </> : detailView === "price-zone" ? <PriceZoneDetailsPage
        summary={priceZoneSeats}
        liveActiveZone={liveActiveZone}
        onBack={closeDetail}
      /> : detailView === "scanner" ? <ScannerStatusPage snapshot={scannerStatus} onBack={closeDetail} /> : <PortfolioPerformanceDetail
        initialTab={performanceInitialTab}
        onBack={closeDetail}
      />}
    </>,
    host,
  ) : null;
}
