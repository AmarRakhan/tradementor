import { proxyCloud } from "@/lib/cloud-proxy";

export async function GET(request: Request) {
  return proxyCloud(request, "/v1/me/preferences/interface", "GET");
}

export async function PUT(request: Request) {
  return proxyCloud(request, "/v1/me/preferences/interface", "PUT");
}
