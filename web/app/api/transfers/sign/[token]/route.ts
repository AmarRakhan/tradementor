import { proxyCloudPublic } from "@/lib/cloud-proxy";

export async function GET(_request: Request, context: { params: Promise<{ token: string }> }) {
  const { token } = await context.params;
  return proxyCloudPublic(`/v1/transfers/signing/${encodeURIComponent(token)}`, "GET");
}

export async function POST(request: Request, context: { params: Promise<{ token: string }> }) {
  const { token } = await context.params;
  return proxyCloudPublic(`/v1/transfers/signing/${encodeURIComponent(token)}`, "POST", await request.text());
}
