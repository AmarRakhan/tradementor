import { proxyCloud } from "@/lib/cloud-proxy";

const CLOUD_PATH = "/v1/me/aster/positions/close-profitable";
const VALID_SCOPES = new Set(["ALL", "LONG", "SHORT"]);

export async function POST(request: Request) {
  const requestUrl = new URL(request.url);

  // Tradecentrum intentionally means ALL when it omits side. Normalize that here so
  // the Cloud API never receives an ambiguous bulk-close request. Portfolio Snapshot
  // supplies LONG/SHORT explicitly and that scope is preserved end-to-end.
  const scope = (requestUrl.searchParams.get("side") ?? "ALL").trim().toUpperCase();
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
