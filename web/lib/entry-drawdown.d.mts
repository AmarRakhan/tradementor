export type DrawdownSide = { avgMaxDrawdownPct: number | null; count: number; recentAvgMaxDrawdownPct: number | null; recentCount: number };
export type EntryDrawdown = { long: DrawdownSide; short: DrawdownSide; refreshing: boolean; complete: boolean; windowDays: number; recentDays: number };
export function formatDrawdown(pct: number | null | undefined): string;
export function drawdownCaption(side: DrawdownSide | null | undefined, refreshing: boolean, recentDays?: number): string;
export function normalizeDrawdown(payload: unknown): EntryDrawdown;
