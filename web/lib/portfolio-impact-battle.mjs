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

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
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

export function dominancePresentation(score = 0) {
  const normalized = clamp(finite(score) ?? 0, -100, 100);
  const roundedScore = Math.round(normalized);
  const longShare = Math.round(clamp(50 + normalized * 0.46, 4, 96));
  const shortShare = 100 - longShare;
  const stateIndex = Math.round(clamp((normalized + 100) / 12.5, 0, 16));
  let status = "IN EVENWICHT";
  if (normalized >= 70) status = "LONGS DOMINEREN";
  else if (normalized >= 35) status = "LONGS DRUKKEN HARDER";
  else if (normalized >= 12) status = "LONGS DRUKKEN LICHT HARDER";
  else if (normalized <= -70) status = "SHORTS DOMINEREN";
  else if (normalized <= -35) status = "SHORTS DRUKKEN HARDER";
  else if (normalized <= -12) status = "SHORTS DRUKKEN LICHT HARDER";
  return { score: roundedScore, longShare, shortShare, stateIndex, status, barLabel: "MARKTDRUK" };
}

function livePressure(longDelta, shortDelta, longExposure, shortExposure, equityBasis) {
  const longBasis = Math.max(Math.abs(longExposure), 1);
  const shortBasis = Math.max(Math.abs(shortExposure), 1);
  const longRate = longDelta / longBasis;
  const shortRate = shortDelta / shortBasis;
  const absoluteMovement = Math.abs(longDelta) + Math.abs(shortDelta);
  const dollarNoiseFloor = Math.max(0.02, equityBasis * 0.00025);
  if (absoluteMovement <= dollarNoiseFloor) return { bias: 0, longShare: 50 };
  const observedRateMovement = Math.abs(longRate) + Math.abs(shortRate);
  if (observedRateMovement <= EPSILON) return { bias: 0, longShare: 50 };
  const edge = longRate - shortRate;
  const directionalEdge = clamp(edge / observedRateMovement, -1, 1);
  const confidence = clamp((absoluteMovement - dollarNoiseFloor) / Math.max(dollarNoiseFloor * 4, 0.05), 0, 1);
  const bias = clamp(Math.tanh(directionalEdge * 1.32) * confidence, -1, 1);
  const longShare = clamp(50 + bias * 42, 8, 92);
  return { bias, longShare };
}

export function deriveBattleMetrics({ longPnl = 0, shortPnl = 0, longDelta = 0, shortDelta = 0, longExposure = 0, shortExposure = 0, equity = 0, dominanceScore = null } = {}) {
  const netPnl = longPnl + shortPnl;
  const equityBasis = Math.max(Math.abs(equity), 100);
  const momentumWeight = 1.35;
  const longScore = longPnl + longDelta * momentumWeight;
  const shortScore = shortPnl + shortDelta * momentumWeight;
  const bothPositive = longPnl > 0 && shortPnl > 0;
  const bothNegative = longPnl < 0 && shortPnl < 0;
  const nearZero = Math.abs(longPnl) + Math.abs(shortPnl) < Math.max(0.05, equityBasis * 0.00001);
  const state = nearZero ? "BALANCED" : bothPositive ? "BOTH_POSITIVE" : bothNegative ? "BOTH_NEGATIVE" : longPnl >= 0 ? "LONG_DOMINANT" : "SHORT_DOMINANT";

  const explicitDominanceScore = dominanceScore === null || dominanceScore === undefined || dominanceScore === "" ? null : finite(dominanceScore);
  if (explicitDominanceScore !== null) {
    const market = dominancePresentation(explicitDominanceScore);
    return {
      netPnl,
      longScore,
      shortScore,
      longShare: market.longShare,
      shortShare: market.shortShare,
      motionBias: market.score / 100,
      intensity: clamp(Math.abs(market.score) / 100, 0.18, 1),
      state,
      status: market.status,
      barLabel: market.barLabel,
      dominanceScore: market.score,
      stateIndex: market.stateIndex,
    };
  }

  const pressure = livePressure(longDelta, shortDelta, longExposure, shortExposure, equityBasis);
  const motionBias = pressure.bias;
  const roundedLongShare = Math.round(pressure.longShare);
  const shortShare = 100 - roundedLongShare;
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
    barLabel: "LIVE DRUK",
  };
}
