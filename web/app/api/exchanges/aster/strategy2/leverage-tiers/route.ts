import { proxyStrategy2Live } from "@/lib/secure-strategy2-live";

export async function GET(request: Request) {
  const url = new URL(request.url);
  return proxyStrategy2Live(request, `/v1/me/aster/strategy2/leverage-tiers${url.search}`, "GET");
}
