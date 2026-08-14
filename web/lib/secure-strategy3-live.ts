const noStore = { "cache-control": "no-store" };

/** Forward only an already-authenticated request to the isolated S3 service. */
export async function proxyStrategy3Live(
  request: Request,
  pathname: string,
  method: "GET" | "POST" | "PUT",
) {
  const liveApi = process.env.STRATEGY3_LIVE_API_URL?.replace(/\/$/, "");
  if (!liveApi) {
    return Response.json(
      { detail: "De geïsoleerde Strategy-3-liveomgeving is nog niet gekoppeld" },
      { status: 503, headers: noStore },
    );
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
        "X-TradeMentor-Client-Mode": "strategy3-live",
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body || undefined,
    });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") ?? "application/json", ...noStore },
    });
  } catch {
    return Response.json(
      { detail: "De Strategy-3-liveomgeving is tijdelijk niet bereikbaar" },
      { status: 503, headers: noStore },
    );
  }
}
