"use client";
import { useEffect,useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
type Event={eventId:string;lastDetectedAt?:string;errorCode?:string;category?:string;component?:string;recoveryAction?:string;status?:string};
type Health={status:string;lastSuccessfulScan?:string;yourBot:{found:number;autoRecovered:number;softwareFixed:number;open:number;safetyHolds:number};platform:{activeBots:number;trackedBots:number;autoRecovered:number;openIncidents:number};incidents:Event[]};
const label={OK:"🟢 Alles OK",RECOVERED:"🟠 Probleem hersteld",ACTION_REQUIRED:"🔴 Actie nodig"} as Record<string,string>;
const when=(v?:string)=>v?new Date(v).toLocaleString("nl-NL",{dateStyle:"short",timeStyle:"medium"}):"Nog niet bewezen";
export function BotHealthCard(){const [data,setData]=useState<Health|null>(null);const [open,setOpen]=useState(false);
 useEffect(()=>{let alive=true;const load=()=>authenticatedRequest("/api/bot-health").then(v=>{if(alive)setData(v as Health)}).catch(()=>{});load();const id=window.setInterval(load,12000);return()=>{alive=false;window.clearInterval(id)}},[]);
 if(!data)return <section className="bot-health-card"><h3>BOT HEALTH</h3><p>Healthinformatie wordt geladen…</p></section>;
 const y=data.yourBot,p=data.platform;return <section className={`bot-health-card ${data.status.toLowerCase()}`}><header><h3>BOT HEALTH</h3><strong>{label[data.status]||"🔴 Actie nodig"}</strong></header>
 <div className="bot-health-columns"><div><h4>Jouw bot</h4><span>Laatste succesvolle scan <b>{when(data.lastSuccessfulScan)}</b></span><span>Problemen gevonden vandaag <b>{y.found}</b></span><span>Automatisch hersteld vandaag <b>{y.autoRecovered}</b></span><span>Softwarefixes vandaag <b>{y.softwareFixed}</b></span><span>Open problemen <b>{y.open}</b></span><span>Safety holds <b>{y.safetyHolds}</b></span></div>
 <div><h4>Platform</h4><span>Actieve bots <b>{p.activeBots}</b></span><span>Gevolgde bots <b>{p.trackedBots}</b></span><span>Automatisch hersteld vandaag <b>{p.autoRecovered}</b></span><span>Open incidenten <b>{p.openIncidents}</b></span></div></div>
 <button type="button" onClick={()=>setOpen(!open)}>Bekijk rapport</button>{open&&<div className="bot-health-report">{data.incidents.length?data.incidents.map(e=><p key={e.eventId}><time>{when(e.lastDetectedAt)}</time> · <b>{e.errorCode||e.category}</b> · {e.component} · {e.recoveryAction||"geen automatische actie"} · <strong>{e.status==="SOFTWARE_FIXED"?"✓ softwarefix":e.status==="AUTO_RECOVERED"?"✓ automatisch hersteld":e.status}</strong></p>):<p>Vandaag zijn geen reliability-incidenten geregistreerd.</p>}</div>}</section>}
