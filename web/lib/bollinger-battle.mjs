export const BOLLINGER_SCORE_MIN = 0;
export const BOLLINGER_SCORE_MAX = 100;
export const BOLLINGER_NEUTRAL = 50;

const INTERVALS = Object.freeze({
  '1m': '1m',
  '5m': '5m',
  '15m': '15m',
  '1h': '1h',
  '4h': '4h',
  '24h': '1d',
});

export function clampBollingerScore(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return BOLLINGER_NEUTRAL;
  return Math.min(BOLLINGER_SCORE_MAX, Math.max(BOLLINGER_SCORE_MIN, number));
}

export function bollingerScore(price, lower, upper) {
  const p = Number(price);
  const lo = Number(lower);
  const hi = Number(upper);
  if (!Number.isFinite(p) || !Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) return null;
  return clampBollingerScore(((p - lo) / (hi - lo)) * 100);
}

export function scoreToTimelineTime(score, durationSeconds) {
  const duration = Number(durationSeconds);
  if (!Number.isFinite(duration) || duration <= 0) return 0;
  return duration * clampBollingerScore(score) / 100;
}

export function timeframeToAsterInterval(timeframe) {
  return INTERVALS[timeframe] ?? '15m';
}

export function transitionDurationMs(fromScore, toScore) {
  const delta = Math.abs(clampBollingerScore(toScore) - clampBollingerScore(fromScore));
  return Math.round(Math.min(850, Math.max(320, 320 + delta * 9)));
}

export function shouldAnimateScore(fromScore, toScore, deadband = 0.35) {
  return Math.abs(clampBollingerScore(toScore) - clampBollingerScore(fromScore)) >= Math.max(0, Number(deadband) || 0);
}

export function battleStatus(score) {
  const normalized = clampBollingerScore(score);
  if (normalized > 51) return 'LONGS DRUKKEN HARDER';
  if (normalized < 49) return 'SHORTS DRUKKEN HARDER';
  return 'IN EVENWICHT';
}

export function legacyPressureOverrideToBollingerScore(score) {
  const pressure = Math.min(100, Math.max(-100, Number(score) || 0));
  return (pressure + 100) / 2;
}
