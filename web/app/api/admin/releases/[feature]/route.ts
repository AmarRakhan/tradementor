import { proxyCloud } from "@/lib/cloud-proxy";

export async function PUT(request: Request, context: { params: Promise<{ feature: string }> }) {
  const { feature } = await context.params;
  const body = await request.text();
  return proxyCloud(request, `/v1/admin/releases/${encodeURIComponent(feature)}`, "PUT", body);
}
