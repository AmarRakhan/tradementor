import { proxyCloud } from "@/lib/cloud-proxy";

export async function POST(request: Request, context: { params: Promise<{ roundId: string }> }) {
  const { roundId } = await context.params;
  if (!/^[a-f0-9]{24}$/.test(roundId)) return Response.json({ detail: "Ronde niet gevonden" }, { status: 404 });
  return proxyCloud(request, `/v1/me/aster/profit-close-rounds/${roundId}/resume`, "POST");
}
