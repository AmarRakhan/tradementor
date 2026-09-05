export type PortfolioBattleState = "LONG_DOMINANT" | "SHORT_DOMINANT" | "BALANCED" | "BOTH_POSITIVE" | "BOTH_NEGATIVE";

export type PortfolioBattleMetrics = {
  netPnl: number;
  longScore: number;
  shortScore: number;
  longShare: number;
  shortShare: number;
  motionBias: number;
  intensity: number;
  state: PortfolioBattleState;
  status: string;
  barLabel: string;
};

export function positionExposure(position: unknown): number;
export function deriveBattleMetrics(input?: {
  longPnl?: number;
  shortPnl?: number;
  longDelta?: number;
  shortDelta?: number;
  longExposure?: number;
  shortExposure?: number;
  equity?: number;
}): PortfolioBattleMetrics;
