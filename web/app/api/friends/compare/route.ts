import { proxyCloud } from "@/lib/cloud-proxy";

export async function GET(request: Request) {
  const search = new URL(request.url).search;
  return proxyCloud(request, `/v1/me/friends/compare${search}`, "GET");
}
