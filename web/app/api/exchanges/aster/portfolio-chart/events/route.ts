import { proxyCloud } from "@/lib/cloud-proxy";

export async function GET(request: Request) {
  const url = new URL(request.url);
  return proxyCloud(request, `/v1/me/aster/portfolio-chart/events${url.search}`, "GET");
}
