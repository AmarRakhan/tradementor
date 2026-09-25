import { proxyCloud } from "@/lib/cloud-proxy";

export async function GET(request: Request, context: { params: Promise<{ friendId: string }> }) {
  const { friendId } = await context.params;
  return proxyCloud(request, `/v1/me/friends/${encodeURIComponent(friendId)}`, "GET");
}
