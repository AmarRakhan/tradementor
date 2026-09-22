import { proxyCloud } from "@/lib/cloud-proxy";

export async function GET(request: Request) {
  const source = new URL(request.url);
  const timeframe = source.searchParams.get("timeframe") || "15m";
  const limit = source.searchParams.get("limit") || "180";
  const query = new URLSearchParams({ timeframe, limit });
  return proxyCloud(request, `/v1/me/aster/portfolio-equity/chart?${query.toString()}`, "GET");
}
