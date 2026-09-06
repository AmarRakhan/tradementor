import { proxyCloud } from "@/lib/cloud-proxy";

/**
 * Aster status is production-owned. Strategy 1 and Strategy 3 are retired and
 * must never be merged into the live Aster status response.
 */
export async function GET(request: Request) {
  const response = await proxyCloud(request, "/v1/me/aster/status", "GET");
  if (!response.ok) return response;
  try {
    const payload = await response.json() as Record<string, unknown>;
    const strategy2 = payload.strategy2 && typeof payload.strategy2 === "object" ? payload.strategy2 as Record<string, unknown> : null;
    if (!strategy2 || strategy2.multiBbReport || !strategy2.multiBb || typeof strategy2.multiBb !== "object") {
      return Response.json(payload, { status: response.status });
    }
    return Response.json({ ...payload, strategy2: { ...strategy2, multiBbReport: strategy2.multiBb } }, { status: response.status });
  } catch {
    return response;
  }
}
