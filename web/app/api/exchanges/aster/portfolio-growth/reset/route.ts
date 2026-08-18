import { proxyCloud } from "@/lib/cloud-proxy";
export async function POST(request: Request) { return proxyCloud(request, "/v1/me/aster/portfolio-growth/reset", "POST"); }
