export type DominancePresentation = {
  score: number;
  longShare: number;
  shortShare: number;
  stateIndex: number;
  status: string;
  barLabel: string;
};
export type PortfolioBattleMetrics = {
  netPnl: number;
  longScore: number;
  shortScore: number;
  longShare: number;
  shortShare: number;
  motionBias: number;
  intensity: number;
  state: string;
  status: string;
  barLabel: string;
  dominanceScore?: number;
  stateIndex?: number;
};
export function positionExposure(position: unknown): number;
export function dominancePresentation(score?: number): DominancePresentation;
export function deriveBattleMetrics(input?: {
  longPnl?: number;
  shortPnl?: number;
  longDelta?: number;
  shortDelta?: number;
  longExposure?: number;
  shortExposure?: number;
  equity?: number;
  dominanceScore?: number | null;
}): PortfolioBattleMetrics;
