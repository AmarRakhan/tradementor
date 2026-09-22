import { proxyCloud } from "@/lib/cloud-proxy";

export async function GET(request: Request) {
  const source = new URL(request.url);
  const timeframe = source.searchParams.get("timeframe") || "15m";
  const query = new URLSearchParams({ timeframe });
  return proxyCloud(request, `/v1/me/aster/portfolio-equity/backtest?${query.toString()}`, "GET");
}
