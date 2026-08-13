import { proxyCloud } from "@/lib/cloud-proxy";
export async function GET(request: Request) { return proxyCloud(request, "/v1/me/aster/strategy3/readiness", "GET"); }
