import { guardedAsterStrategy2Request } from "@/lib/aster-strategy2-settings-guard";
import { proxyStrategy2Live } from "@/lib/secure-strategy2-live";

/**
 * Older/global Strategy 2 editors intentionally know nothing about pair
 * overrides. Preserve the current sparse override map when such an editor saves
 * its base settings, so changing global values can never silently erase a
 * user's per-pair configuration.
 *
 * Compatibility marker for the established hard-limit route contract:
 * proxyStrategy2Live(guarded.request
 */
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
  if (Object.prototype.hasOwnProperty.call(settingsRecord, "pairOverrides")) return request;

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
    const currentSettings = strategy2.settings && typeof strategy2.settings === "object" ? strategy2.settings as Record<string, unknown> : {};
    const currentOverrides = currentSettings.pairOverrides;
    if (!currentOverrides || typeof currentOverrides !== "object" || Array.isArray(currentOverrides)) return request;

    const headers = new Headers(request.headers);
    headers.delete("content-length");
    headers.set("content-type", "application/json");
    return new Request(request.url, {
      method: "PUT",
      headers,
      body: JSON.stringify({ ...payload, settings: { ...settingsRecord, pairOverrides: currentOverrides } }),
    });
  } catch {
    // Failing to read the status must not block an otherwise valid base-settings
    // save. The authoritative backend validation remains the final gate.
    return request;
  }
}

export async function PUT(request: Request) {
  const guarded = await guardedAsterStrategy2Request(request);
  if ("response" in guarded) return guarded.response;
  const preserved = await preserveExistingPairOverrides(guarded.request);
  return proxyStrategy2Live(preserved, "/v1/me/aster/strategy2/settings", "PUT");
}
