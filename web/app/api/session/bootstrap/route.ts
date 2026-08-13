const CLOUD_API = "https://tradementor-api-604335232956.europe-west4.run.app";

export async function POST(request: Request) {
  const authorization = request.headers.get("authorization");
  if (!authorization?.startsWith("Bearer ")) {
    return Response.json({ detail: "Firebase ID-token ontbreekt" }, { status: 401 });
  }

  try {
    const upstream = await fetch(`${CLOUD_API}/v1/me/bootstrap`, {
      method: "POST",
      headers: { Authorization: authorization, "Content-Type": "application/json" },
      body: "{}",
    });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json" },
    });
  } catch {
    return Response.json({ detail: "TradeMentor Cloud is tijdelijk niet bereikbaar" }, { status: 503 });
  }
}
