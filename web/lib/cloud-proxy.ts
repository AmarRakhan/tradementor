const CLOUD_API = "https://tradementor-api-604335232956.europe-west4.run.app";

export async function proxyCloud(request: Request, pathname: string, method: "GET" | "POST" | "PUT", bodyOverride?: string) {
  const authorization = request.headers.get("authorization");
  if (!authorization?.startsWith("Bearer ")) {
    return Response.json({ detail: "Firebase ID-token ontbreekt" }, { status: 401 });
  }
  try {
    const body = bodyOverride ?? (method === "GET" ? undefined : await request.text());
    const upstream = await fetch(`${CLOUD_API}${pathname}`, {
      method,
      cache: "no-store",
      headers: {
        Authorization: authorization,
        "Cache-Control": "no-cache, no-store, max-age=0",
        Pragma: "no-cache",
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(request.headers.get("x-tradementor-admin-device") ? {"X-TradeMentor-Admin-Device":request.headers.get("x-tradementor-admin-device")!} : {}),
      },
      body: body || undefined,
    });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "application/json",
        "Cache-Control": "no-store, no-cache, max-age=0, must-revalidate",
        Pragma: "no-cache",
        Expires: "0",
      },
    });
  } catch {
    return Response.json(
      { detail: "TradeMentor Cloud is tijdelijk niet bereikbaar" },
      { status: 503, headers: { "Cache-Control": "no-store, no-cache, max-age=0, must-revalidate" } },
    );
  }
}
