export const LIQUIDATION_RISK_THRESHOLDS = Object.freeze({
  greenMin: 25,
  yellowMin: 15,
  orangeMin: 8,
});

function finitePositive(value) {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

export function liquidationDistancePercent(position) {
  if (!position || typeof position !== "object") return null;
  const markPrice = finitePositive(position.markPrice ?? position.mark);
  const liquidationPrice = finitePositive(position.liquidationPrice);
  const side = String(position.side ?? position.positionSide ?? "").toUpperCase();
  if (markPrice === null || liquidationPrice === null || !["LONG", "SHORT"].includes(side)) return null;
  const distance = side === "LONG"
    ? (markPrice - liquidationPrice) / markPrice * 100
    : (liquidationPrice - markPrice) / markPrice * 100;
  return Number.isFinite(distance) && distance >= 0 ? distance : null;
}

export function liquidationRiskTone(distancePercent) {
  if (!Number.isFinite(distancePercent)) return "unknown";
  if (distancePercent >= LIQUIDATION_RISK_THRESHOLDS.greenMin) return "safe";
  if (distancePercent >= LIQUIDATION_RISK_THRESHOLDS.yellowMin) return "caution";
  if (distancePercent >= LIQUIDATION_RISK_THRESHOLDS.orangeMin) return "high";
  return "critical";
}

export function mostCriticalLiquidationPosition(positions) {
  if (!Array.isArray(positions)) return null;
  let critical = null;
  for (const position of positions) {
    const distancePercent = liquidationDistancePercent(position);
    if (distancePercent === null) continue;
    if (critical === null || distancePercent < critical.distancePercent) {
      critical = { position, distancePercent, tone: liquidationRiskTone(distancePercent) };
    }
  }
  return critical;
}
