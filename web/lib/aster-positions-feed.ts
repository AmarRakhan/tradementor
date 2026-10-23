// Build 644: the Aster page already polls the account snapshot. Markets reads the
// open positions from that same snapshot instead of fetching the account again.

type Listener = (positions: unknown[]) => void;

let latest: unknown[] = [];
let known = false;
const listeners = new Set<Listener>();

export function publishAsterPositions(positions: unknown) {
  if (!Array.isArray(positions)) return;
  latest = positions;
  known = true;
  for (const listener of listeners) {
    try { listener(latest); } catch { /* a listener must never break the feed */ }
  }
}

export function asterPositionsKnown() {
  return known;
}

export function currentAsterPositions() {
  return latest;
}

export function subscribeAsterPositions(listener: Listener) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
