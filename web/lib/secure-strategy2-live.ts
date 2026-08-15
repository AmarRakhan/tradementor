const noStore = { "cache-control": "no-store" };

const strategy2Paths = new Set([
  "/v1/me/aster/strategy2/settings",
  "/v1/me/aster/strategy2/simulate",
  "/v1/me/aster/strategy2/readiness",
  "/v1/me/aster/strategy2/canary",
  "/v1/me/aster/strategy2/start",
  "/v1/me/aster/strategy2/stop",
]);

/**
 * Route only Strategy 2's authenticated endpoints to the configured API.
 * The generic site proxy remains read-only; server-side readiness, canary,
 * ownership and live-enable checks stay authoritative for every live action.
 */
export async function proxyStrategy2Live(request: Request, pathname: string, method: "GET" | "POST" | "PUT") {
  if (!strategy2Paths.has(pathname)) {
    return Response.json({ detail: "Onbekende Strategy-2-route" }, { status: 404, headers: noStore });
  }
  const liveApi = process.env.CLOUD_API_URL?.replace(/\/$/, "");
  if (!liveApi) {
    return Response.json({ detail: "De Strategy-2-liveomgeving is nog niet gekoppeld" }, { status: 503, headers: noStore });
  }
  const authorization = request.headers.get("authorization");
  if (!authorization?.startsWith("Bearer ")) {
    return Response.json({ detail: "Firebase ID-token ontbreekt" }, { status: 401, headers: noStore });
  }
  try {
    const body = method === "GET" ? undefined : await request.text();
    const upstream = await fetch(`${liveApi}${pathname}`, {
      method,
      headers: {
        Authorization: authorization,
        "X-TradeMentor-Client-Mode": "strategy2-live",
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body || undefined,
    });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") ?? "application/json", ...noStore },
    });
  } catch {
    return Response.json({ detail: "De Strategy-2-liveomgeving is tijdelijk niet bereikbaar" }, { status: 503, headers: noStore });
  }
}
