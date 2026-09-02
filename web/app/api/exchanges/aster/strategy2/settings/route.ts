import { guardedAsterStrategy2Request } from "@/lib/aster-strategy2-settings-guard";
import { proxyStrategy2Live } from "@/lib/secure-strategy2-live";

export async function PUT(request: Request) {
  const guarded = await guardedAsterStrategy2Request(request);
  if ("response" in guarded) return guarded.response;
  return proxyStrategy2Live(guarded.request, "/v1/me/aster/strategy2/settings", "PUT");
}
