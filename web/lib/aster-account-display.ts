export type AsterAccountDisplay = {
  reliable: boolean;
  equityNumber: number | null;
  availableNumber: number | null;
  equity: string;
  available: string;
  maintenanceMarginPercent: number | null;
  maintenanceValue: string;
  maintenanceDetail: string;
  liquidationRiskPercent: number | null;
  liquidationValue: string;
  liquidationTone: "safe" | "caution" | "high" | "critical" | "unknown";
  liquidationDetail: string;
  liquidationRiskSource: "ASTER_ACCOUNT_RATIO" | "SERVER_RECONSTRUCTED" | "UNKNOWN";
  positionCountIncluded: number | null;
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
  const displayable = Boolean(data) && configured;
  const equityNumber = displayable ? number(data?.equity) : null;
  const availableNumber = displayable ? number(data?.availableBalance) : null;
  const maintenanceMarginPercent = displayable ? number(data?.maintenanceMarginPct) : null;
  const rawLiquidation = displayable ? number(data?.liquidationRiskPct) : null;
  const liquidationRiskPercent = rawLiquidation === null ? null : Math.max(0, Math.min(100, rawLiquidation));
  const sourceRaw = displayable ? String(data?.liquidationRiskSource ?? "") : "";
  const liquidationRiskSource = sourceRaw === "ASTER_ACCOUNT_RATIO" || sourceRaw === "SERVER_RECONSTRUCTED" ? sourceRaw : "UNKNOWN";
  const included = displayable ? number(data?.positionCountIncluded) : null;
  const liquidationTone = liquidationRiskPercent === null ? "unknown"
    : liquidationRiskPercent < 25 ? "safe"
      : liquidationRiskPercent < 50 ? "caution"
        : liquidationRiskPercent < 75 ? "high" : "critical";
  const liquidationDetail = liquidationRiskPercent === null
    ? "Geen bevestigde cross-account liquidatieratio"
    : liquidationRiskPercent < 25 ? "Ruim veilig · 100% is liquidatiegrens"
      : liquidationRiskPercent < 50 ? "Verhoogd · bewaak cross margin"
        : liquidationRiskPercent < 75 ? "Hoog risico · dicht bij liquidatie"
          : "Kritiek · 100% is liquidatiegrens";
  const maintenanceDetail = maintenanceMarginPercent === null ? "Geen bevestigde gewogen MMR" : "Gewogen maintenance-rate over bruto cross exposure";
  return {
    reliable,
    equityNumber,
    availableNumber,
    equity: formatUsd(equityNumber),
    available: formatUsd(availableNumber),
    maintenanceMarginPercent,
    maintenanceValue: formatPercent(maintenanceMarginPercent),
    maintenanceDetail,
    liquidationRiskPercent,
    liquidationValue: formatPercent(liquidationRiskPercent),
    liquidationTone,
    liquidationDetail,
    liquidationRiskSource,
    positionCountIncluded: included === null ? null : Math.round(included),
  };
}
