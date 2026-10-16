import { guardedAsterStrategy2Request } from "@/lib/aster-strategy2-settings-guard";
import { proxyStrategy2Live } from "@/lib/secure-strategy2-live";

/** Fields unknown to older/global editors must survive their saves. */
const preserveKeys = [
  "pairOverrides",
  // Preserve optional entry filters when an older/global form submits only legacy fields.
  "entryFilterMode",
  "extremeSpikeLevel",
  "extremeSpikeLongTimeframe",
  "extremeSpikeShortTimeframe",
  "takeProfitMode",
  "portfolioTpPercent",
  "portfolioTpInputMode",
  "portfolioTpValue",
  "portfolioTpBaseMode",
  "portfolioTpCustomBaseEquity",
  "resetSeatsAfterPortfolioTp",
  "portfolioTpResetLongSlots",
  "portfolioTpResetShortSlots",
  "longDcaDistance",
  "shortDcaDistance",
  "longDcaMarginUsd",
  "shortDcaMarginUsd",
  "longDcaAmount",
  "shortDcaAmount",
  "maxDcaLong",
  "maxDcaShort",
  "longMaxDca",
  "shortMaxDca",
  "longTakeProfitValue",
  "shortTakeProfitValue",
  "takeProfitLong",
  "takeProfitShort",
  "profitLockLadderEnabled",
  "profitLockLevels",
  "profitLockPrimarySide",
  "maximumLeverage",
  "entrySizingMode",
  "entryNotionalUsd",
  "entryNotionalLongUsd",
  "entryNotionalShortUsd",
  "entryMarginLongUsd",
  "entryMarginShortUsd",
  "stopLossEnabled",
  "stopLossMode",
  "stopLossLong",
  "stopLossShort",
] as const;

async function preserveExistingPairOverrides(request: Request) {
  let payload: Record<string, unknown>;
  try {
    payload = await request.clone().json() as Record<string, unknown>;
  } catch {
    return request;
  }
  const settings = payload.settings;
  if (!settings || typeof settings !== "object" || Array.isArray(settings)) return request;
  const settingsRecord = settings as Record<string, unknown>;
  const missing = preserveKeys.filter((key) => !Object.prototype.hasOwnProperty.call(settingsRecord, key));
  if (!missing.length) return request;

  const missingSpikeMode = !Object.prototype.hasOwnProperty.call(settingsRecord, "entryFilterMode");
  const safeFailure = () => new Response(JSON.stringify({error:"Filterinstellingen niet verifieerbaar; opslaan geblokkeerd."}), {status:409,headers:{"content-type":"application/json"}});
  const authorization = request.headers.get("authorization");
  if (!authorization?.startsWith("Bearer ")) return missingSpikeMode ? safeFailure() : request;
  try {
    const readCurrent = () => fetch(new URL("/api/exchanges/aster", request.url), {
      method: "GET",
      headers: { Authorization: authorization },
      cache: "no-store",
    });
    let status = await readCurrent();
    // A transient status failure must not strand an otherwise valid TP edit.
    // Retry this READ once, never a settings PUT. Still fail closed if the
    // canonical account settings cannot be verified after the second read.
    if (!status.ok && missingSpikeMode && (status.status === 429 || status.status >= 500)) {
      status = await readCurrent();
    }
    if (!status.ok) return missingSpikeMode ? safeFailure() : request;
    const snapshot = await status.json() as Record<string, unknown>;
    const strategy2 = snapshot.strategy2 && typeof snapshot.strategy2 === "object" ? snapshot.strategy2 as Record<string, unknown> : {};
    const current = strategy2.settings && typeof strategy2.settings === "object" ? strategy2.settings as Record<string, unknown> : {};
    if (missingSpikeMode && (!strategy2.settings || typeof strategy2.settings !== "object" || Array.isArray(strategy2.settings))) return safeFailure();
    const merged = { ...settingsRecord };
    for (const key of missing) {
      if (Object.prototype.hasOwnProperty.call(current, key)) merged[key] = current[key];
    }
    // Legacy editors do not know entryFilterMode. They must never switch an
    // existing Extreme Spike account to Bollinger by sending a stale BB flag.
    // Explicit mode updates from the new selector remain authoritative.
    if (!Object.prototype.hasOwnProperty.call(settingsRecord, "entryFilterMode") &&
        current.entryFilterMode === "EXTREME_SPIKE") {
      merged.entryFilterMode = "EXTREME_SPIKE";
      merged.bollingerEntryFilter15mEnabled = false;
    }
    const headers = new Headers(request.headers);
    headers.delete("content-length");
    headers.set("content-type", "application/json");
    return new Request(request.url, {
      method: "PUT",
      headers,
      body: JSON.stringify({ ...payload, settings: merged }),
    });
  } catch {
    return missingSpikeMode ? safeFailure() : request;
  }
}

export async function PUT(request: Request) {
  const guarded = await guardedAsterStrategy2Request(request);
  if ("response" in guarded) return guarded.response;
  const preserved = await preserveExistingPairOverrides(guarded.request);
  if (preserved instanceof Response) return preserved;
  if (preserved === guarded.request) {
    return proxyStrategy2Live(guarded.request, "/v1/me/aster/strategy2/settings", "PUT");
  }
  return proxyStrategy2Live(preserved, "/v1/me/aster/strategy2/settings", "PUT");
}
