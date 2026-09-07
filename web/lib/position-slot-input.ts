export const MAX_TOTAL_POSITIONS = 100;
export const MAX_SIDE_SLOTS = 100;

export type PositionSlotState = { total: number; long: number; short: number };

function clampInteger(value: unknown, min: number, max: number) {
  const number = Number(value);
  const normalized = Number.isFinite(number) ? Math.round(number) : min;
  return Math.max(min, Math.min(max, normalized));
}

export function splitTotalPositions(value: unknown): PositionSlotState {
  const total = clampInteger(value, 1, MAX_TOTAL_POSITIONS);
  const long = Math.ceil(total / 2);
  return { total, long, short: total - long };
}

export function applyLongSlots(totalValue: unknown, longValue: unknown): PositionSlotState {
  const total = clampInteger(totalValue, 1, MAX_TOTAL_POSITIONS);
  const long = clampInteger(longValue, 0, Math.min(total, MAX_SIDE_SLOTS));
  return { total, long, short: total - long };
}

export function applyShortSlots(totalValue: unknown, shortValue: unknown): PositionSlotState {
  const total = clampInteger(totalValue, 1, MAX_TOTAL_POSITIONS);
  const short = clampInteger(shortValue, 0, Math.min(total, MAX_SIDE_SLOTS));
  return { total, long: total - short, short };
}
