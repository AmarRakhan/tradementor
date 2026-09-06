import { guardedAsterStrategy2Request } from "@/lib/aster-strategy2-settings-guard";
import { proxyStrategy2Live } from "@/lib/secure-strategy2-live";

/** Fields unknown to older/global editors must survive their saves. */
const preserveKeys = [
  "pairOverrides",
  "takeProfitMode",
  "portfolioTpPercent",
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
] as const;

async function preserveExtendedSettings(request: Request) {
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

  const authorization = request.headers.get("authorization");
  if (!authorization?.startsWith("Bearer ")) return request;
  try {
    const status = await fetch(new URL("/api/exchanges/aster", request.url), {
      method: "GET",
      headers: { Authorization: authorization },
      cache: "no-store",
    });
    if (!status.ok) return request;
    const snapshot = await status.json() as Record<string, unknown>;
    const strategy2 = snapshot.strategy2 && typeof snapshot.strategy2 === "object" ? snapshot.strategy2 as Record<string, unknown> : {};
    const current = strategy2.settings && typeof strategy2.settings === "object" ? strategy2.settings as Record<string, unknown> : {};
    const merged = { ...settingsRecord };
    for (const key of missing) {
      if (Object.prototype.hasOwnProperty.call(current, key)) merged[key] = current[key];
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
    return request;
  }
}

export async function PUT(request: Request) {
  const guarded = await guardedAsterStrategy2Request(request);
  if ("response" in guarded) return guarded.response;
  const preserved = await preserveExtendedSettings(guarded.request);
  return proxyStrategy2Live(preserved, "/v1/me/aster/strategy2/settings", "PUT");
}
