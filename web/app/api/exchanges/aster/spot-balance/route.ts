import { proxyCloud } from "@/lib/cloud-proxy";

export async function GET(request: Request) {
  const asset = new URL(request.url).searchParams.get("asset")?.toUpperCase() || "USDC";
  if (asset !== "USDC" && asset !== "USDT") {
    return Response.json({ detail: "Alleen USDC en USDT worden ondersteund" }, { status: 422, headers: { "Cache-Control": "no-store" } });
  }
  return proxyCloud(request, `/v1/me/aster/spot-balance?asset=${asset}`, "GET");
}
