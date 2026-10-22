import { proxyCloud } from "@/lib/cloud-proxy";

export const dynamic = "force-dynamic";

// SHORT Recovery 2.0: saves settings only. The server worker applies them; no order is placed here.
export async function PUT(request: Request) {
  return proxyCloud(request, "/v1/me/aster/position-loss-auto-hedge/short-recovery", "PUT");
}
