import { proxyCloud } from "@/lib/cloud-proxy";

export async function GET(request: Request) {
  const search = new URL(request.url).search;\n  return proxyCloud(request, `/v1/me/friends/insights${search}`, "GET");
}

export async function POST(request: Request) {
  return proxyCloud(request, "/v1/me/friends/insights", "POST");
}
