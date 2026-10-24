export const ASTER_MIN_NOTIONAL: number;
export type Dist = "EQUAL" | "ASCENDING" | "STEEP";
export type PreviewInput = { steps: number; totalPct: number; distribution: Dist; rebuySteps: number; rehedgePct: number; safetyNetPct: number };
export type PreviewEvent = { type: "SELL" | "REBUY" | "NOODREM"; qty: number };
export type PreviewPoint = { move: number; price: number; shortQty: number; net: number; events: PreviewEvent[] };
export function partWeights(n: number, dist?: Dist): number[];
export function fitParts(input: { hedgeUsd: number; steps: number; totalPct: number; distribution?: Dist; minNotional?: number }): number;
export function stakeForParts(input: { parts: number; totalPct: number; distribution?: Dist; leverage: number; maxHedgePct?: number; minNotional?: number }): number;
export function adviseStake(input: PreviewInput & { leverage: number; maxHedgePct?: number; stake: number }): {
  recommended: number; rows: { parts: number; stake: number }[]; current: number | null; equalAll: number;
};
export function adviseSettings(input: { stake: number; leverage: number; maxHedgePct?: number; totalPct?: number; goal?: "SAFE" | "BALANCE" | "PROFIT" }):
  | { ok: false; hedgeUsd: number; reason: string }
  | { ok: true; hedgeUsd: number; settings: PreviewInput; smallestUsd: number; backUsd: number; backFits: boolean };
export function scenarioPath(scenario: string, input: PreviewInput): number[];
export function simulate(settings: PreviewInput, scenario?: "RECOVER" | "FALL" | "CHOP", opts?: { maxHedgePct?: number; side?: "SHORT" | "LONG" }): {
  points: PreviewPoint[]; result: number; fixed: number; maxNet: number; maxNetFrom: number; maxNetTo: number;
  noodrem: number | null; noodremAt: number;
};
