import { mostCriticalLiquidationPosition } from "./liquidation-risk.mjs";

export type AsterAccountDisplay = {
  reliable: boolean;
  equityNumber: number | null;
  availableNumber: number | null;
  equity: string;
  available: string;
  liquidationDistancePercent: number | null;
  liquidationValue: string;
  liquidationTone: "safe" | "caution" | "high" | "critical" | "unknown";
  liquidationDetail: string;
};

function number(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatUsd(value: number | null): string {
  return value === null ? "—" : new Intl.NumberFormat("nl-NL", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}

function formatPercent(value: number | null): string {
  return value === null ? "—" : `${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)}%`;
}

export function deriveAsterAccountDisplay({ data, serverConfirmed, error, updatedAt, now = Date.now() }: { data: Record<string, unknown> | null; serverConfirmed: boolean; error?: string; updatedAt: number | null; now?: number }): AsterAccountDisplay {
  const configured = data?.configured === true;
  const fresh = updatedAt !== null && now - updatedAt < 120_000;
  const reliable = Boolean(data) && configured && serverConfirmed && !error && fresh;
  const equityNumber = reliable ? number(data?.equity) : null;
  const availableNumber = reliable ? number(data?.availableBalance) : null;
  const rawPositions = reliable && Array.isArray(data?.positions) ? data.positions as Array<Record<string, unknown>> : [];
  const liquidationRisk = mostCriticalLiquidationPosition(rawPositions);
  const liquidationDistancePercent = liquidationRisk?.distancePercent ?? null;
  const liquidationTone = liquidationRisk?.tone ?? "unknown";
  const liquidationDetail = liquidationRisk ? `${String(liquidationRisk.position?.symbol ?? "Aster")} · afstand tot liquidatie` : "Geen betrouwbare Aster liquidatieafstand";
  return {
    reliable,
    equityNumber,
    availableNumber,
    equity: formatUsd(equityNumber),
    available: formatUsd(availableNumber),
    liquidationDistancePercent,
    liquidationValue: formatPercent(liquidationDistancePercent),
    liquidationTone,
    liquidationDetail,
  };
}
