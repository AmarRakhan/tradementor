export const PORTFOLIO_ZONE_SEATS_PER_STEP = 5;
export const PORTFOLIO_ZONE_MAX_TOTAL_SLOTS = 100;

function count(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.round(number)) : null;
}

export function derivePortfolioZoneInstruction(input = {}) {
  const rawZone = input.zoneIndex;
  const zone = rawZone === null || rawZone === undefined || rawZone === "" ? null : Number.isInteger(Number(rawZone)) ? Number(rawZone) : null;
  const longSlots = count(input.longSlots);
  const shortSlots = count(input.shortSlots);
  const activeLong = count(input.activeLong);
  const activeShort = count(input.activeShort);
  const perStep = Math.max(1, count(input.seatsPerStep) ?? PORTFOLIO_ZONE_SEATS_PER_STEP);
  const maxTotal = Math.max(1, count(input.maxTotalSlots) ?? PORTFOLIO_ZONE_MAX_TOTAL_SLOTS);

  if (zone === null || longSlots === null || shortSlots === null || activeLong === null || activeShort === null) {
    return {
      status: "UNAVAILABLE",
      zoneIndex: zone,
      side: null,
      amount: 0,
      longSlots,
      shortSlots,
      activeLong,
      activeShort,
      targetLongSlots: longSlots,
      targetShortSlots: shortSlots,
      desiredLongSlots: longSlots,
      desiredShortSlots: shortSlots,
      requiredFreeSeats: 0,
      reason: "Live zone- of stoeldata ontbreekt.",
    };
  }

  const safeLongSlots = Math.max(longSlots, activeLong);
  const safeShortSlots = Math.max(shortSlots, activeShort);
  if (zone === 0) {
    return {
      status: "OK",
      zoneIndex: zone,
      side: null,
      amount: 0,
      longSlots: safeLongSlots,
      shortSlots: safeShortSlots,
      activeLong,
      activeShort,
      targetLongSlots: safeLongSlots,
      targetShortSlots: safeShortSlots,
      desiredLongSlots: safeLongSlots,
      desiredShortSlots: safeShortSlots,
      requiredFreeSeats: 0,
      reason: "Neutrale zone: huidige stoelverdeling behouden.",
    };
  }

  const side = zone > 0 ? "SHORT" : "LONG";
  const requiredFreeSeats = Math.min(15, Math.abs(zone) * perStep);
  const sideSlots = side === "LONG" ? safeLongSlots : safeShortSlots;
  const activeSide = side === "LONG" ? activeLong : activeShort;
  const freeSide = Math.max(0, sideSlots - activeSide);
  const desiredSideSlots = activeSide + requiredFreeSeats;
  const desiredLongSlots = side === "LONG" ? desiredSideSlots : safeLongSlots;
  const desiredShortSlots = side === "SHORT" ? desiredSideSlots : safeShortSlots;
  const delta = desiredSideSlots - sideSlots;

  if (delta === 0) {
    return {
      status: "OK",
      zoneIndex: zone,
      side,
      amount: 0,
      longSlots: safeLongSlots,
      shortSlots: safeShortSlots,
      activeLong,
      activeShort,
      targetLongSlots: safeLongSlots,
      targetShortSlots: safeShortSlots,
      desiredLongSlots,
      desiredShortSlots,
      requiredFreeSeats,
      reason: `${requiredFreeSeats} vrije ${side}-stoelen staan klaar voor deze zone.`,
    };
  }

  if (delta < 0) {
    const amount = Math.abs(delta);
    return {
      status: "REMOVE",
      zoneIndex: zone,
      side,
      amount,
      longSlots: safeLongSlots,
      shortSlots: safeShortSlots,
      activeLong,
      activeShort,
      targetLongSlots: side === "LONG" ? desiredSideSlots : safeLongSlots,
      targetShortSlots: side === "SHORT" ? desiredSideSlots : safeShortSlots,
      desiredLongSlots,
      desiredShortSlots,
      requiredFreeSeats,
      reason: `Deze zone vraagt ${requiredFreeSeats} vrije ${side}-stoelen; ${freeSide} zijn vrij.`,
    };
  }

  const currentTotal = safeLongSlots + safeShortSlots;
  const room = Math.max(0, maxTotal - currentTotal);
  const amount = Math.min(delta, room);
  if (amount <= 0) {
    return {
      status: "BLOCKED",
      zoneIndex: zone,
      side,
      amount: delta,
      longSlots: safeLongSlots,
      shortSlots: safeShortSlots,
      activeLong,
      activeShort,
      targetLongSlots: safeLongSlots,
      targetShortSlots: safeShortSlots,
      desiredLongSlots,
      desiredShortSlots,
      requiredFreeSeats,
      reason: `Deze zone vraagt ${delta} extra ${side}-stoelen, maar de limiet van ${maxTotal} totaal is bereikt.`,
    };
  }

  const targetLongSlots = side === "LONG" ? safeLongSlots + amount : safeLongSlots;
  const targetShortSlots = side === "SHORT" ? safeShortSlots + amount : safeShortSlots;
  return {
    status: amount === delta ? "ADD" : "PARTIAL_ADD",
    zoneIndex: zone,
    side,
    amount,
    remaining: Math.max(0, delta - amount),
    longSlots: safeLongSlots,
    shortSlots: safeShortSlots,
    activeLong,
    activeShort,
    targetLongSlots,
    targetShortSlots,
    desiredLongSlots,
    desiredShortSlots,
    requiredFreeSeats,
    reason: amount === delta
      ? `Deze zone vraagt ${requiredFreeSeats} vrije ${side}-stoelen; ${freeSide} zijn vrij.`
      : `Er is ruimte voor ${amount} van de ${delta} benodigde extra ${side}-stoelen.`,
  };
}
