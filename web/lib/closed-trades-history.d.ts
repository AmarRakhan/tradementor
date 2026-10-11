export type ClosedTradeRecord = {
  recordId?: string; id?: string; exchangeTradeId?: string; symbol?: string; side?: string;
  closedAt?: string | number | null; openedAt?: string | null; timestampMs?: number | null;
  marginUsd?: number | null; executedMarginUsd?: number | null; initialMarginUsd?: number | null;
  realizedPnlUsd?: number | null;
};
export function closedTradeTime(row?: ClosedTradeRecord): number | null;
export function verifiedClosedTradeMargin(row?: ClosedTradeRecord): number | null;
export function closedTradeDurationMs(row?: ClosedTradeRecord): number | null;
export function closedTradeStableKey(row?: ClosedTradeRecord): string;
export function uniqueClosedTrades<T extends ClosedTradeRecord>(rows?: T[]): T[];
