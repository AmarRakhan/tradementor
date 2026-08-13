import { proxyCloud } from "@/lib/cloud-proxy";

export async function POST(request: Request, context: { params: Promise<{ symbol: string }> }) {
  const { symbol } = await context.params;
  return proxyCloud(request, `/v1/me/positions/${encodeURIComponent(symbol)}/close`, "POST");
}
