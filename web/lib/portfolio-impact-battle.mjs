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

function livePressure(longDelta, shortDelta, longExposure, shortExposure, equityBasis) {
  // Compare the *direction* of recent P&L movement after normalizing each side by its own book size.
  // Crucially, do not use a fixed normalized-return floor: with highly leveraged Aster books (millions
  // of notional against a small equity balance) that floor previously swallowed real $1-$20 moves and
  // forced the widget to 50/50 forever. Noise filtering is therefore done in account dollars first.
  const longBasis = Math.max(Math.abs(longExposure), 1);
  const shortBasis = Math.max(Math.abs(shortExposure), 1);
  const longRate = longDelta / longBasis;
  const shortRate = shortDelta / shortBasis;

  const absoluteMovement = Math.abs(longDelta) + Math.abs(shortDelta);
  const dollarNoiseFloor = Math.max(0.02, equityBasis * 0.00025);
  if (absoluteMovement <= dollarNoiseFloor) return { bias: 0, longShare: 50 };

  const observedRateMovement = Math.abs(longRate) + Math.abs(shortRate);
  if (observedRateMovement <= EPSILON) return { bias: 0, longShare: 50 };

  // Rising LONG P&L is bullish pressure; rising SHORT P&L is bearish pressure.
  const edge = longRate - shortRate;
  const directionalEdge = clamp(edge / observedRateMovement, -1, 1);
  const confidence = clamp((absoluteMovement - dollarNoiseFloor) / Math.max(dollarNoiseFloor * 4, 0.05), 0, 1);
  const bias = clamp(Math.tanh(directionalEdge * 1.32) * confidence, -1, 1);
  const longShare = clamp(50 + bias * 42, 8, 92);
  return { bias, longShare };
}

export function deriveBattleMetrics({ longPnl = 0, shortPnl = 0, longDelta = 0, shortDelta = 0, longExposure = 0, shortExposure = 0, equity = 0 } = {}) {
  const netPnl = longPnl + shortPnl;
  const equityBasis = Math.max(Math.abs(equity), 100);
  const momentumWeight = 1.35;
  const longScore = longPnl + longDelta * momentumWeight;
  const shortScore = shortPnl + shortDelta * momentumWeight;
  const bothPositive = longPnl > 0 && shortPnl > 0;
  const bothNegative = longPnl < 0 && shortPnl < 0;
  const nearZero = Math.abs(longPnl) + Math.abs(shortPnl) < Math.max(0.05, equityBasis * 0.00001);

  // Absolute P&L remains descriptive context only. The battle itself is live pressure.
  const state = nearZero ? "BALANCED" : bothPositive ? "BOTH_POSITIVE" : bothNegative ? "BOTH_NEGATIVE" : longPnl >= 0 ? "LONG_DOMINANT" : "SHORT_DOMINANT";
  const pressure = livePressure(longDelta, shortDelta, longExposure, shortExposure, equityBasis);
  const motionBias = pressure.bias;
  const roundedLongShare = Math.round(pressure.longShare);
  const shortShare = 100 - roundedLongShare;
  const barLabel = "LIVE DRUK";

  let status = "IN EVENWICHT";
  if (motionBias >= 0.12) status = "LONGS DRUKKEN HARDER";
  else if (motionBias <= -0.12) status = "SHORTS DRUKKEN HARDER";

  const normalizedLongMove = Math.abs(longDelta) / Math.max(Math.abs(longExposure), equityBasis, 1);
  const normalizedShortMove = Math.abs(shortDelta) / Math.max(Math.abs(shortExposure), equityBasis, 1);
  const intensity = clamp((normalizedLongMove + normalizedShortMove) / 0.0006, 0.18, 1);
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
