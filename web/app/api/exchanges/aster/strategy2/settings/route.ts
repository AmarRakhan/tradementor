import { proxyStrategy2Live } from "@/lib/secure-strategy2-live";
export async function PUT(request: Request) { return proxyStrategy2Live(request, "/v1/me/aster/strategy2/settings", "PUT"); }
