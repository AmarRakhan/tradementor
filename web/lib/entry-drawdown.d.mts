export type DrawdownSide = { avgMaxDrawdownPct: number | null; count: number };
export type EntryDrawdown = { long: DrawdownSide; short: DrawdownSide; refreshing: boolean; complete: boolean };
export function formatDrawdown(pct: number | null | undefined): string;
export function drawdownCaption(side: DrawdownSide | null | undefined, refreshing: boolean): string;
export function normalizeDrawdown(payload: unknown): EntryDrawdown;
