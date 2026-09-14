import { proxyCloud } from "@/lib/cloud-proxy";

export async function PUT(request: Request, context: { params: Promise<{ symbol: string }> }) {
  const { symbol } = await context.params;
  return proxyCloud(request, `/v1/me/aster/strategy2/smart-rescue/${encodeURIComponent(symbol)}/extend`, "PUT");
}
