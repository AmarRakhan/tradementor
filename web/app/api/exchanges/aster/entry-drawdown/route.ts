import { proxyCloud } from "@/lib/cloud-proxy";

// Build 652: gem. max drawdown vanaf instap per kant (alleen lezen; de server ververst op de achtergrond).
export async function GET(request: Request) {
  return proxyCloud(request, "/v1/me/aster/entry-drawdown", "GET");
}
