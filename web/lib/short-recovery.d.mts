export type RecoveryCheck = { ok: true; steps: number; totalPct: number; stepPct: number; sellPct: number } | { ok: false; message: string };
export type LadderRow = { step: number; dropPct: number; price: number; remainingPct: number };
export type RecoveryRow = {
  symbol: string; phase: string; cycle: number; progress: string;
  anchor: number | null; hedgePct: number | null; event: string;
};
export function validateRecoverySettings(stepsRaw: unknown, totalPctRaw: unknown): RecoveryCheck;
export function recoveryLadder(stepsRaw: unknown, totalPctRaw: unknown, anchor?: number): LadderRow[];
export function recoveryEventLabel(event: unknown): string;
export function recoveryRows(pairs: unknown, liveMode: boolean): RecoveryRow[];
export function unwindBadge(pair: unknown): { label: string; detail: string; cls: string } | null;
