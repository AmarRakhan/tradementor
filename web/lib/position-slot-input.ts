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

export function applyLongSlots(shortValue: unknown, longValue: unknown): PositionSlotState {
  const short = clampInteger(shortValue, 0, MAX_SIDE_SLOTS);
  const long = clampInteger(longValue, 0, Math.min(MAX_SIDE_SLOTS, MAX_TOTAL_POSITIONS - short));
  return { total: long + short, long, short };
}

export function applyShortSlots(longValue: unknown, shortValue: unknown): PositionSlotState {
  const long = clampInteger(longValue, 0, MAX_SIDE_SLOTS);
  const short = clampInteger(shortValue, 0, Math.min(MAX_SIDE_SLOTS, MAX_TOTAL_POSITIONS - long));
  return { total: long + short, long, short };
}
