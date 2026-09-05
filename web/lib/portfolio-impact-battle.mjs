const EPSILON = 1e-9;

function finite(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function readNumber(record, keys) {
  if (!record || typeof record !== "object") return null;
  for (const key of keys) {
    const value = finite(record[key]);
    if (value !== null) return value;
  }
  return null;
}

export function positionExposure(position) {
  if (!position || typeof position !== "object") return 0;
  const direct = readNumber(position, ["notional", "notionalUsd", "notionalUSDT", "positionNotional", "exposure", "exposureUsd"]);
  if (direct !== null && direct !== 0) return Math.abs(direct);
  const size = readNumber(position, ["size", "qty", "quantity", "positionAmt"]);
  const mark = readNumber(position, ["markPrice", "price", "entry", "entryPrice"]);
  if (size !== null && mark !== null) return Math.abs(size * mark);
  const margin = readNumber(position, ["margin", "marginUsd", "initialMargin", "positionInitialMargin"]);
  const leverage = readNumber(position, ["leverage"]);
  if (margin !== null && leverage !== null) return Math.abs(margin * leverage);
  return Math.abs(margin ?? 0);
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function livePressure(longDelta, shortDelta, equityBasis) {
  // A rising LONG P&L is bullish pressure; a rising SHORT P&L is bearish pressure.
  // The difference between both deltas therefore expresses which side is winning terrain now.
  // A small equity-scaled floor prevents tiny quote noise from creating fake 95/5 battles.
  const edge = longDelta - shortDelta;
  const observedMovement = Math.abs(longDelta) + Math.abs(shortDelta);
  const noiseFloor = Math.max(equityBasis * 0.00025, 0.5);
  const scale = Math.max(observedMovement, noiseFloor);
  const bias = observedMovement <= Math.max(equityBasis * 0.00001, 0.02)
    ? 0
    : clamp(Math.tanh((edge / scale) * 1.18), -1, 1);
  const longShare = clamp(50 + bias * 42, 8, 92);
  return { bias, longShare };
}

export function deriveBattleMetrics({ longPnl = 0, shortPnl = 0, longDelta = 0, shortDelta = 0, longExposure = 0, shortExposure = 0, equity = 0 } = {}) {
  const netPnl = longPnl + shortPnl;
  const equityBasis = Math.max(Math.abs(equity), Math.abs(longExposure) * 0.04 + Math.abs(shortExposure) * 0.04, 100);
  const momentumWeight = 1.35;
  const longScore = longPnl + longDelta * momentumWeight;
  const shortScore = shortPnl + shortDelta * momentumWeight;
  const bothPositive = longPnl > 0 && shortPnl > 0;
  const bothNegative = longPnl < 0 && shortPnl < 0;
  const nearZero = Math.abs(longPnl) + Math.abs(shortPnl) < Math.max(0.05, equityBasis * 0.00001);

  // Absolute P&L remains descriptive context only. The battle itself is live pressure.
  let state = nearZero ? "BALANCED" : bothPositive ? "BOTH_POSITIVE" : bothNegative ? "BOTH_NEGATIVE" : longPnl >= 0 ? "LONG_DOMINANT" : "SHORT_DOMINANT";
  const pressure = livePressure(longDelta, shortDelta, equityBasis);
  const motionBias = pressure.bias;
  const longShare = pressure.longShare;
  const roundedLongShare = Math.round(longShare);
  const shortShare = 100 - roundedLongShare;
  const barLabel = "LIVE DRUK";

  let status = "IN EVENWICHT";
  if (motionBias >= 0.12) status = "LONGS DRUKKEN HARDER";
  else if (motionBias <= -0.12) status = "SHORTS DRUKKEN HARDER";

  const intensity = clamp((Math.abs(longDelta) + Math.abs(shortDelta)) / Math.max(equityBasis * 0.0015, 1), 0.18, 1);
  return {
    netPnl,
    longScore,
    shortScore,
    longShare: roundedLongShare,
    shortShare,
    motionBias,
    intensity,
    state,
    status,
    barLabel,
  };
}
