export function normalizeLiquidationRisk(value) {
  if (value === null || value === undefined) return null;
  const parsed = typeof value === "number"
    ? value
    : Number(String(value).replace("%", "").replace(",", ".").trim());
  if (!Number.isFinite(parsed)) return null;
  return Math.max(0, Math.min(100, parsed));
}

export function liquidationNeedleDegrees(value) {
  const risk = normalizeLiquidationRisk(value);
  return risk === null ? 0 : risk * 1.8;
}

export function liquidationRiskRemaining(value) {
  const risk = normalizeLiquidationRisk(value);
  return risk === null ? null : Math.max(0, 100 - risk);
}

export function liquidationRiskTone(value) {
  const risk = normalizeLiquidationRisk(value);
  if (risk === null) return "unknown";
  if (risk < 25) return "safe";
  if (risk < 50) return "caution";
  if (risk < 75) return "high";
  return "critical";
}

export function formatLiquidationRisk(value) {
  const risk = normalizeLiquidationRisk(value);
  if (risk === null) return "—";
  return `${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: risk % 1 === 0 ? 0 : 2, maximumFractionDigits: 2 }).format(risk)}%`;
}
