import { proxyCloud } from "@/lib/cloud-proxy";

/**
 * Aster status is production-owned. Strategy 1 and Strategy 3 are retired and
 * must never be merged into the live Aster status response.
 */
export async function GET(request: Request) {
  return proxyCloud(request, "/v1/me/aster/status", "GET");
}
