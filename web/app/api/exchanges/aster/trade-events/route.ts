import { proxyCloud } from "@/lib/cloud-proxy";

export async function GET(request: Request) {
  const source = new URL(request.url);
  const query = new URLSearchParams();
  for (const key of ["symbol", "side", "closed_at_ms", "anchor_at_ms"]) {
    const value = source.searchParams.get(key);
    if (value) query.set(key, value);
  }
  return proxyCloud(request, `/v1/me/aster/trade-events?${query}`, "GET");
}
