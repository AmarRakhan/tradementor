import { proxyCloud } from "@/lib/cloud-proxy";

// Build 648: the full trade journal plus settings history as one JSON document (for the download button).
export async function GET(request: Request) {
  return proxyCloud(request, "/v1/me/aster/trade-journal/export", "GET");
}
