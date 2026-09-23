import { proxyCloud } from "@/lib/cloud-proxy";

export async function PUT(request: Request, context: { params: Promise<{ featureKey: string }> }) {
  const { featureKey } = await context.params;
  return proxyCloud(request, "/v1/admin/releases/" + encodeURIComponent(featureKey), "PUT");
}
