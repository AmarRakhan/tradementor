import { proxyCloud } from "@/lib/cloud-proxy";

export async function GET(request: Request) {
  return proxyCloud(request, "/v1/me/agent/status", "GET");
}

export async function POST(request: Request) {
  return proxyCloud(request, "/v1/me/agent/provision", "POST");
}
