import { proxyCloud } from "@/lib/cloud-proxy";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const raw = url.searchParams.get("percentage") ?? "25";
  if (!["25", "50", "75", "100"].includes(raw)) {
    return Response.json({ detail: "Invalid profit close percentage" }, { status: 422 });
  }
  return proxyCloud(request, `/v1/me/aster/positions/manual-profit-close-plan?percentage=${raw}`, "GET");
}
