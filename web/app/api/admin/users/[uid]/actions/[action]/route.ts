import {proxyCloud} from "@/lib/cloud-proxy";
export async function POST(request:Request,{params}:{params:Promise<{uid:string;action:string}>}){const {uid,action}=await params;return proxyCloud(request,`/v1/admin/users/${encodeURIComponent(uid)}/actions/${encodeURIComponent(action)}`,"POST")}
