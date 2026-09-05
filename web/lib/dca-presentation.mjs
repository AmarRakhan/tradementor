function finiteNonNegative(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 ? n : null;
}
function count(value) {
  const n = finiteNonNegative(value);
  return n === null ? null : Math.max(0, Math.round(n));
}
export function deriveDcaPresentation(input = {}) {
  const runtime = count(input.runtimeDcaCount);
  const position = input.positionDcaCountReliable === true ? count(input.positionDcaCount) : null;
  const ladder = input.ladderAvailable === true ? count(input.ladderFilledDcaCount) : null;
  const confirmed = count(input.confirmedFillDcaCount);
  const fallback = count(input.fallbackDcaCount);
  const reliable = [runtime, position, ladder, confirmed].filter(v => v !== null);
  const filledDcaCount = reliable.length ? Math.max(...reliable) : fallback;
  let source = "unknown";
  if (confirmed !== null && filledDcaCount === confirmed && runtime !== null && confirmed !== runtime) source = "confirmed-fills";
  else if (runtime !== null && filledDcaCount === runtime) source = "runtime";
  else if (position !== null && filledDcaCount === position) source = "position";
  else if (ladder !== null && filledDcaCount === ladder) source = "ladder";
  else if (confirmed !== null && filledDcaCount === confirmed) source = "confirmed-fills";
  else if (fallback !== null) source = "fallback";
  const priceCandidate = finiteNonNegative(input.nextDcaPrice);
  const nextDcaPrice = priceCandidate !== null && priceCandidate > 0 ? priceCandidate : null;
  const rawNextDcaNumber = count(input.nextDcaNumber);
  const nextDcaNumber = nextDcaPrice !== null && filledDcaCount !== null ? filledDcaCount + 1 : rawNextDcaNumber;
  const nextDcaDistancePct = input.nextDcaDistancePct === null || input.nextDcaDistancePct === undefined || input.nextDcaDistancePct === "" ? null : (Number.isFinite(Number(input.nextDcaDistancePct)) ? Number(input.nextDcaDistancePct) : null);
  const signals = [runtime, position, ladder, confirmed].filter(v => v !== null);
  const countMismatch = signals.length > 1 && new Set(signals).size > 1;
  const nextMismatch = nextDcaPrice !== null && filledDcaCount !== null && rawNextDcaNumber !== null && rawNextDcaNumber !== filledDcaCount + 1;
  return { filledDcaCount, nextDcaNumber, nextDcaPrice, nextDcaDistancePct, dcaCountReliable: reliable.length > 0, source, mismatch: countMismatch || nextMismatch };
}
