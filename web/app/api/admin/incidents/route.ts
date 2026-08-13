import {proxyCloud} from "@/lib/cloud-proxy";
export async function GET(request:Request){return proxyCloud(request,"/v1/admin/incidents","GET")}
