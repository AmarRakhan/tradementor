import { proxyCloud } from "@/lib/cloud-proxy";

export const dynamic = "force-dynamic";

export async function PUT(request: Request, context: { params: Promise<{ symbol: string }> }) {
  const { symbol } = await context.params;
  return proxyCloud(
    request,
    `/v1/me/aster/position-loss-auto-hedge/pairs/${encodeURIComponent(symbol)}/rehedge`,
    "PUT",
  );
}
