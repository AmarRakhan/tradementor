import { simulateStrategy3Paper } from "@/lib/aster-strategy3-paper";
export async function POST(request:Request){try{const body=await request.json() as {settings?:Record<string,unknown>};return Response.json(simulateStrategy3Paper(body.settings||{}))}catch(error){return Response.json({error:error instanceof Error?error.message:"Ongeldige simulatie-instellingen"},{status:400})}}
