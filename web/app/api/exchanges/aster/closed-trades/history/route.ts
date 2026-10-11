import { proxyCloud } from "@/lib/cloud-proxy";

export async function GET(request: Request) {
  const incoming = new URL(request.url).searchParams;
  const params = new URLSearchParams();
  if (incoming.has("limit")) params.set("limit", incoming.get("limit") ?? "");
  if (incoming.has("cursor")) params.set("cursor", incoming.get("cursor") ?? "");
  if (incoming.has("scope")) params.set("scope", incoming.get("scope") ?? "");
  const query = params.toString();
  return proxyCloud(request, `/v1/me/aster/closed-trades/history${query ? `?${query}` : ""}`, "GET");
}
