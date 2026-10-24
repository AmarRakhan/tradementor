import { proxyCloud } from "@/lib/cloud-proxy";

// Build 648: newest Trade Historie rows straight from the journal (Firestore only, no Aster call).
export async function GET(request: Request) {
  const raw = Number(new URL(request.url).searchParams.get("limit") || "100");
  const limit = Number.isFinite(raw) ? Math.min(300, Math.max(1, Math.round(raw))) : 100;
  return proxyCloud(request, `/v1/me/aster/trade-journal/recent?limit=${limit}`, "GET");
}
