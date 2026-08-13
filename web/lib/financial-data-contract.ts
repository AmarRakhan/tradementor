export type FinancialMetricOrigin = "aster_direct" | "aster_aggregate" | "tradementor_calculated";

export type FinancialMetricDefinition = {
  label: string;
  origin: FinancialMetricOrigin;
  source: string;
  formula?: string;
  tradingDecision: boolean;
};

/** Central registry: no calculated Aster metric may be displayed anonymously. */
export const ASTER_FINANCIAL_DATA_CONTRACT = {
  portfolioEquity: { label: "Portfoliowaarde", origin: "aster_direct", source: "totalMarginBalance", tradingDecision: true },
  availableBalance: { label: "Available to trade", origin: "aster_direct", source: "availableBalance", tradingDecision: true },
  unrealizedPnl: { label: "Open PnL", origin: "aster_direct", source: "totalUnrealizedProfit / unRealizedProfit", tradingDecision: true },
  maintenanceMargin: { label: "Maintenance margin", origin: "aster_direct", source: "totalMaintMargin", tradingDecision: true },
  activeTradeCapital: { label: "Active Trade Capital", origin: "aster_aggregate", source: "positionInitialMargin", formula: "sum(positionInitialMargin) for active Aster positions", tradingDecision: false },
  activePositionCount: { label: "Actieve posities", origin: "aster_aggregate", source: "positionAmt", formula: "count(positionAmt != 0)", tradingDecision: false },
  maintenanceRatio: { label: "Maintenance", origin: "tradementor_calculated", source: "totalMaintMargin + totalMarginBalance", formula: "totalMaintMargin / totalMarginBalance * 100", tradingDecision: false },
  positionDisplayReturn: { label: "Bruto positie-resultaat", origin: "tradementor_calculated", source: "unRealizedProfit + mark notional", formula: "unRealizedProfit / abs(positionAmt * markPrice) * 100", tradingDecision: false },
} as const satisfies Record<string, FinancialMetricDefinition>;

export function optionalFinancialNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function positionDisplayReturnPercent(pnl: number | null, notional: number | null): number | null {
  if (pnl === null || notional === null || notional <= 0) return null;
  return pnl / notional * 100;
}
