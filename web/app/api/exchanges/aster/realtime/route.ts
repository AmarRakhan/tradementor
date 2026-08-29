import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
const CLOUD_API = process.env.TRADEMENTOR_CLOUD_API_URL || "https://tradementor-api-604335232956.europe-west4.run.app";

export async function GET(request: NextRequest) {
  const authorization = request.headers.get("authorization");
  if (!authorization?.startsWith("Bearer ")) return new Response("Unauthorized", { status: 401 });
  const upstream = await fetch(`${CLOUD_API}/v1/me/aster/realtime/events`, {
    headers: { Authorization: authorization, Accept: "text/event-stream" },
    cache: "no-store",
    signal: request.signal,
  });
  if (!upstream.ok || !upstream.body) return new Response("Realtime feed unavailable", { status: upstream.status || 502 });
  return new Response(upstream.body, { status: 200, headers: {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
  }});
}
