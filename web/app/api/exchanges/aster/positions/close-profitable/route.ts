import { proxyCloud } from "@/lib/cloud-proxy";

const CLOUD_PATH = "/v1/me/aster/positions/close-profitable";
const VALID_SCOPES = new Set(["ALL", "LONG", "SHORT"]);

export async function POST(request: Request) {
  const requestUrl = new URL(request.url);
  const requestedSide = requestUrl.searchParams.get("side");

  // Tradecentrum historically omits the side parameter and intentionally means ALL.
  // When a caller explicitly supplies a side (Portfolio Snapshot LONG/SHORT), preserve
  // that scope across the Next -> Cloud proxy boundary. Never downgrade an explicit
  // scoped request to ALL.
  if (requestedSide === null) {
    return proxyCloud(request, CLOUD_PATH, "POST");
  }

  const scope = requestedSide.trim().toUpperCase();
  if (!VALID_SCOPES.has(scope)) {
    return Response.json(
      { detail: "Profit close scope moet ALL, LONG of SHORT zijn" },
      { status: 422, headers: { "Cache-Control": "no-store" } },
    );
  }

  return proxyCloud(
    request,
    `${CLOUD_PATH}?side=${encodeURIComponent(scope)}`,
    "POST",
  );
}
