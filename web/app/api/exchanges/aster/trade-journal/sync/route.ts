import { proxyCloud } from "@/lib/cloud-proxy";

// Build 648: one bounded, read-only sync step of the trade journal (the app repeats it until complete).
export async function POST(request: Request) {
  return proxyCloud(request, "/v1/me/aster/trade-journal/sync", "POST", "{}");
}
