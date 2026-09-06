import { proxyCloud } from "@/lib/cloud-proxy";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const destinationId = url.searchParams.get("destinationId") || "";
  return proxyCloud(request, `/v1/me/transfers/quote?destinationId=${encodeURIComponent(destinationId)}`, "GET");
}
