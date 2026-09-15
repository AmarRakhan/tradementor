import { proxyCloud } from "@/lib/cloud-proxy";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  return proxyCloud(request, "/v1/me/aster/portfolio-emergency-hedge", "GET");
}

export async function PUT(request: Request) {
  return proxyCloud(request, "/v1/me/aster/portfolio-emergency-hedge", "PUT");
}
