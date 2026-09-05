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

function safeShare(left, right) {
  const total = Math.abs(left) + Math.abs(right);
  return total <= EPSILON ? 50 : clamp((Math.abs(left) / total) * 100, 6, 94);
}

function normalizedPressure(pnl, delta, exposure, equityBasis) {
  const exposureScale = Math.max(Math.sqrt(Math.max(Math.abs(exposure), 1)), 1);
  const pnlScale = Math.max(Math.sqrt(equityBasis), 10);
  const lossPressure = Math.sqrt(Math.max(-pnl, 0) + 0.25) / pnlScale;
  const adverseMomentum = Math.max(-delta, 0) / Math.max(equityBasis * 0.0015, 1);
  const recoveryRelief = Math.max(delta, 0) / Math.max(equityBasis * 0.0015, 1);
  const exposureContext = Math.log1p(Math.abs(exposure)) / Math.max(Math.log1p(equityBasis * 8), 1);
  return Math.max(0.02, lossPressure * (0.84 + exposureContext * 0.16) + adverseMomentum * 0.18 - recoveryRelief * 0.08 + 1 / exposureScale * 0.005);
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
  let state = "BALANCED";
  let status = "IN EVENWICHT";
  let barLabel = "P&L BIJDRAGE";
  let longShare = 50;
  let motionBias = 0;

  if (nearZero) {
    state = "BALANCED";
  } else if (bothPositive) {
    state = "BOTH_POSITIVE";
    longShare = safeShare(longScore, shortScore);
    const difference = longScore - shortScore;
    motionBias = Math.tanh(difference / Math.max(Math.abs(longScore) + Math.abs(shortScore), equityBasis * 0.002, 1));
    status = Math.abs(longShare - 50) < 6 ? "BEIDE KANTEN DRAGEN BIJ" : longShare > 50 ? "LONGS DRUKKEN OMHOOG" : "SHORTS DRUKKEN OMHOOG";
  } else if (bothNegative) {
    state = "BOTH_NEGATIVE";
    barLabel = "NEGATIEVE DRUK";
    const longDrag = Math.abs(longPnl);
    const shortDrag = Math.abs(shortPnl);
    const longPressure = normalizedPressure(longPnl, longDelta, longExposure, equityBasis);
    const shortPressure = normalizedPressure(shortPnl, shortDelta, shortExposure, equityBasis);
    longShare = clamp(50 + ((longPressure - shortPressure) / Math.max(longPressure + shortPressure, EPSILON)) * 20, 30, 70);
    motionBias = clamp(((longPressure - shortPressure) / Math.max(longPressure + shortPressure, EPSILON)) * 0.42, -0.42, 0.42);
    status = Math.abs(longDrag - shortDrag) < Math.max(0.5, (longDrag + shortDrag) * 0.08)
      ? "BEIDE KANTEN DRUKKEN OMLAAG"
      : shortDrag > longDrag ? "SHORTS DRUKKEN HARDER OMLAAG" : "LONGS DRUKKEN HARDER OMLAAG";
  } else {
    const scale = Math.max(Math.abs(longScore) + Math.abs(shortScore), equityBasis * 0.0025, 1);
    motionBias = Math.tanh((longScore - shortScore) / scale);
    longShare = clamp(50 + motionBias * 42, 6, 94);
    if (longScore > shortScore) {
      state = "LONG_DOMINANT";
      status = longPnl >= 0 ? "LONGS DRUKKEN OMHOOG" : longDelta > 0 ? "LONGS HERSTELLEN" : "LONGS HOUDEN BETER STAND";
    } else if (shortScore > longScore) {
      state = "SHORT_DOMINANT";
      status = shortPnl >= 0 ? "SHORTS DRUKKEN OMHOOG" : shortDelta > 0 ? "SHORTS HERSTELLEN" : "SHORTS HOUDEN BETER STAND";
    }
  }

  const intensity = clamp((Math.abs(longDelta) + Math.abs(shortDelta)) / Math.max(equityBasis * 0.0015, 1), 0.18, 1);
  return {
    netPnl,
    longScore,
    shortScore,
    longShare: Math.round(longShare),
    shortShare: 100 - Math.round(longShare),
    motionBias: clamp(motionBias, -1, 1),
    intensity,
    state,
    status,
    barLabel,
  };
}
