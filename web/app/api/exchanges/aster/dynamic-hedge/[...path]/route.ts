import { proxyCloud } from "@/lib/cloud-proxy";

function cloudPath(request: Request) {
  const url = new URL(request.url);
  const marker = "/api/exchanges/aster/dynamic-hedge/";
  const index = url.pathname.indexOf(marker);
  const suffix = index >= 0 ? url.pathname.slice(index + marker.length) : "state";
  return `/v1/me/aster/dynamic-hedge/${suffix}${url.search}`;
}

export async function GET(request: Request) {
  return proxyCloud(request, cloudPath(request), "GET");
}

export async function PUT(request: Request) {
  return proxyCloud(request, cloudPath(request), "PUT");
}
