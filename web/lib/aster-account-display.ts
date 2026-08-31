export type AsterAccountDisplay = {
  reliable: boolean;
  equityNumber: number | null;
  availableNumber: number | null;
  equity: string;
  available: string;
  liquidationRiskPercent: number | null;
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
  // Read-only values may come from the UID-scoped local snapshot while the fresh
  // server check is still in flight. Keep showing that last confirmed snapshot
  // immediately after reload, but keep `reliable` false so trading actions stay
  // fail-closed until a new server response has been confirmed.
  const displayable = Boolean(data) && configured;
  const equityNumber = displayable ? number(data?.equity) : null;
  const availableNumber = displayable ? number(data?.availableBalance) : null;
  const marginRatio = displayable ? number(data?.marginRatio) : null;
  const maintenanceMargin = displayable ? number(data?.maintenanceMargin) : null;
  const rawRiskPercent = marginRatio !== null
    ? marginRatio * 100
    : equityNumber !== null && equityNumber > 0 && maintenanceMargin !== null
      ? maintenanceMargin / equityNumber * 100
      : null;
  const liquidationRiskPercent = rawRiskPercent === null ? null : Math.max(0, Math.min(100, rawRiskPercent));
  const liquidationTone = liquidationRiskPercent === null ? "unknown"
    : liquidationRiskPercent < 25 ? "safe"
      : liquidationRiskPercent < 50 ? "caution"
        : liquidationRiskPercent < 75 ? "high" : "critical";
  const liquidationDetail = liquidationRiskPercent === null ? "Geen betrouwbare Aster margin ratio" : "0% is ruim · 100% is liquidatiegrens";
  return {
    reliable,
    equityNumber,
    availableNumber,
    equity: formatUsd(equityNumber),
    available: formatUsd(availableNumber),
    liquidationRiskPercent,
    liquidationValue: formatPercent(liquidationRiskPercent),
    liquidationTone,
    liquidationDetail,
  };
}
