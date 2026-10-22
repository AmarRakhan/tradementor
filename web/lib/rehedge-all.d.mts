export const RECOVERY_STATUSES: string[];
export type RehedgeAllItem = Record<string, unknown> & { symbol?: string; outcome?: string; reason?: string };
export type RehedgeAllResult = { found?: number; ordersSent?: number; mode?: string; status?: string; items?: RehedgeAllItem[] };
export type RehedgeAllRow = {
  symbol: string;
  outcome: string;
  label: string;
  longNotional: string;
  shortBefore: string;
  shortAfter: string;
  addedQty: number;
  hedgePercent: string;
};
export type RehedgeAllSummary = {
  found: number;
  protected: number;
  busy: number;
  skipped: number;
  attention: number;
  ordersSent: number;
  testMode: boolean;
  rows: RehedgeAllRow[];
};
export const OUTCOME_GROUPS: Record<"ok" | "busy" | "skipped" | "attention", string[]>;
export function recoveryPairs<T = Record<string, unknown>>(pairs: unknown): T[];
export function outcomeLabel(item: unknown): string;
export function summarizeRehedgeAll(result: unknown): RehedgeAllSummary;
