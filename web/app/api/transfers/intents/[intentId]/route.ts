import { proxyCloud } from "@/lib/cloud-proxy";

export async function GET(request: Request, context: { params: Promise<{ intentId: string }> }) {
  const { intentId } = await context.params;
  return proxyCloud(request, `/v1/me/transfers/intents/${encodeURIComponent(intentId)}`, "GET");
}
