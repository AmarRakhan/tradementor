import { proxyCloud } from "@/lib/cloud-proxy";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const after = Math.max(0, Number(url.searchParams.get("after_ms") || 0) || 0);
  return proxyCloud(request, "/v1/me/notifications/recent?after_ms=" + Math.floor(after), "GET");
}
