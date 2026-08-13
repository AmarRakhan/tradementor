import { proxyCloud } from "@/lib/cloud-proxy";

export async function PUT(request: Request) {
  return proxyCloud(request, "/v1/me/aster/strategy3/settings", "PUT");
}