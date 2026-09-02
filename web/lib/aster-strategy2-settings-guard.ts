const MAX_TOTAL_POSITIONS = 50;
const MAX_LONG_SLOTS = 25;
const MAX_SHORT_SLOTS = 25;
const MAX_DCA = 3;

function finiteInteger(value: unknown, fallback: number) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.round(number) : fallback;
}

export function enforceAsterStrategy2Limits(settings: Record<string, unknown>) {
  const next = { ...settings };
  const hasLong = settings.longSlots !== undefined || settings.maximumLongPositions !== undefined;
  const hasShort = settings.shortSlots !== undefined || settings.maximumShortPositions !== undefined;
  const requestedLong = finiteInteger(settings.longSlots ?? settings.maximumLongPositions, 0);
  const requestedShort = finiteInteger(settings.shortSlots ?? settings.maximumShortPositions, 0);
  const longSlots = Math.max(0, Math.min(MAX_LONG_SLOTS, requestedLong));
  const shortSlots = Math.max(0, Math.min(MAX_SHORT_SLOTS, requestedShort));

  if (hasLong) next.longSlots = longSlots;
  if (hasShort) next.shortSlots = shortSlots;
  if (hasLong || hasShort) next.maximumPositions = Math.max(1, Math.min(MAX_TOTAL_POSITIONS, longSlots + shortSlots));
  else if (settings.maximumPositions !== undefined || settings.maximumPairs !== undefined) {
    next.maximumPositions = Math.max(1, Math.min(MAX_TOTAL_POSITIONS, finiteInteger(settings.maximumPositions ?? settings.maximumPairs, 1)));
  }

  next.maxDca = Math.max(0, Math.min(MAX_DCA, finiteInteger(settings.maxDca ?? settings.longMaxDca, MAX_DCA)));
  next.unlimitedDca = false;
  return next;
}

export async function guardedAsterStrategy2Request(request: Request) {
  let payload: Record<string, unknown>;
  try {
    payload = await request.json() as Record<string, unknown>;
  } catch {
    return { response: new Response(JSON.stringify({ error: "Ongeldige Strategy 2-instellingen." }), { status: 400, headers: { "content-type": "application/json" } }) } as const;
  }

  const rawSettings = payload.settings;
  if (!rawSettings || typeof rawSettings !== "object" || Array.isArray(rawSettings)) {
    return { request: new Request(request.url, { method: request.method, headers: request.headers, body: JSON.stringify(payload) }) } as const;
  }

  const guarded = { ...payload, settings: enforceAsterStrategy2Limits(rawSettings as Record<string, unknown>) };
  return { request: new Request(request.url, { method: request.method, headers: request.headers, body: JSON.stringify(guarded) }) } as const;
}
