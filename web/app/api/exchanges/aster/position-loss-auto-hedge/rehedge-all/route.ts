import { proxyCloud } from "@/lib/cloud-proxy";

export const dynamic = "force-dynamic";

// Re-Hedge All 1.0: one server-side request; the server starts the existing Auto Hedge cycle per Recovery pair.
export async function POST(request: Request) {
  return proxyCloud(request, "/v1/me/aster/position-loss-auto-hedge/rehedge-all", "POST");
}
