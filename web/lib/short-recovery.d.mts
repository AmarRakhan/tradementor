export type RecoveryCheck = { ok: true; steps: number; stepPct: number } | { ok: false; message: string };
export type LadderRow = { step: number; dropPct: number; price: number; remainingPct: number };
export type RecoveryRow = {
  symbol: string; phase: string; cycle: number; progress: string;
  anchor: number | null; hedgePct: number | null; event: string;
};
export function validateRecoverySettings(stepsRaw: unknown, stepPctRaw: unknown): RecoveryCheck;
export function recoveryLadder(stepsRaw: unknown, stepPctRaw: unknown, anchor?: number): LadderRow[];
export function recoveryEventLabel(event: unknown): string;
export function recoveryRows(pairs: unknown, liveMode: boolean): RecoveryRow[];
