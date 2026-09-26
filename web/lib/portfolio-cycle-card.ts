export type PortfolioCycleCardState = {
  active: boolean;
  statusLabel: "Niet ingesteld" | "Actief" | "Bijna eruit" | "Doel bereikt";
  progressPercent: number | null;
  remainingUsd: number | null;
  remainingPercent: number | null;
};

type AnyRecord = Record<string, unknown>;

const record = (value: unknown): AnyRecord =>
  value && typeof value === "object" && !Array.isArray(value) ? value as AnyRecord : {};

const finite = (value: unknown): number | null => {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const firstFinite = (...values: unknown[]): number | null => {
  for (const value of values) {
    const parsed = finite(value);
    if (parsed !== null) return parsed;
  }
  return null;
};

const inactive = (): PortfolioCycleCardState => ({
  active: false,
  statusLabel: "Niet ingesteld",
  progressPercent: null,
  remainingUsd: null,
  remainingPercent: null,
});

export function derivePortfolioCycleCard(payload: unknown): PortfolioCycleCardState {
  const root = record(payload);
  const strategy2 = record(root.strategy2);
  const settings = record(strategy2.settings);
  const multiBb = record(strategy2.multiBb);
  const multiBbReport = record(strategy2.multiBbReport);
  const durableCycle = record(strategy2.multiBbCycle);
  const cycle = Object.keys(durableCycle).length
    ? durableCycle
    : Object.keys(record(multiBb.portfolioCycle)).length
      ? record(multiBb.portfolioCycle)
      : record(multiBbReport.portfolioCycle);

  const takeProfitMode = String(settings.takeProfitMode ?? "").trim().toUpperCase();
  if (takeProfitMode !== "PORTFOLIO") return inactive();

  const baseEquity = firstFinite(cycle.baseEquity, cycle.cycleStartEquity);
  const targetEquity = firstFinite(cycle.targetEquity);
  const account = record(root.account);
  const snapshot = record(root.snapshot);
  const currentEquity = firstFinite(
    cycle.currentEquity,
    root.equity,
    root.portfolioValue,
    account.totalMarginBalance,
    account.marginBalance,
    account.totalWalletBalance,
    snapshot.equity,
    snapshot.portfolioValue,
  );

  if (
    baseEquity === null || targetEquity === null || currentEquity === null
    || baseEquity <= 0 || currentEquity <= 0 || targetEquity <= baseEquity
  ) return inactive();

  const progressPercent = Math.max(0, Math.min(100, ((currentEquity - baseEquity) / (targetEquity - baseEquity)) * 100));
  const remainingUsd = Math.max(0, targetEquity - currentEquity);
  const remainingPercent = currentEquity > 0 ? Math.max(0, (remainingUsd / currentEquity) * 100) : null;
  const statusLabel = progressPercent >= 100 ? "Doel bereikt" : progressPercent >= 80 ? "Bijna eruit" : "Actief";

  return { active: true, statusLabel, progressPercent, remainingUsd, remainingPercent };
}
