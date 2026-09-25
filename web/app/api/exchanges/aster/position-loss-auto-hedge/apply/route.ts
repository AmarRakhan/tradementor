import { proxyCloud } from "@/lib/cloud-proxy";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  return proxyCloud(request, "/v1/me/aster/position-loss-auto-hedge/apply", "POST");
}
