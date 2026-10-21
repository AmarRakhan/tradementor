import { proxyCloud } from "@/lib/cloud-proxy";

// Close Profits 2.1: create a server-recorded round from the confirmed preview.
export async function POST(request: Request) {
  return proxyCloud(request, "/v1/me/aster/profit-close-rounds", "POST");
}
