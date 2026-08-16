export type RecentActivity = Record<string, unknown> & {
  id?: string;
  exchangeTradeId?: string;
  timestampMs?: number;
  executedAt?: string;
};
export function activityTime(row?: RecentActivity): number;
export function stableActivityId(row?: RecentActivity): string;
export function newestActivityFirst(left: RecentActivity, right: RecentActivity): number;
export function sortedActivity<T extends object>(rows: T[] | unknown): T[];
export function pageActivity<T extends object>(rows: T[] | unknown, loadedPages: number, pageSize?: number): T[];
export function reliableReturnPct(row?: object): number | null;
