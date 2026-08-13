import {proxyCloud} from "@/lib/cloud-proxy";
export async function POST(request:Request){return proxyCloud(request,"/v1/admin/device/verify","POST")}
