import { proxyStrategy2Live } from "@/lib/secure-strategy2-live";

export async function POST(request: Request) {
  return proxyStrategy2Live(request, "/v1/me/aster/strategy2/money-grabber/start-round", "POST");
}
