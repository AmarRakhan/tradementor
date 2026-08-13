"use client";
import { useEffect, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

type Report = { id:string; title:string; description:string; status:string; adminNote?:string; createdAt?:string; updatedAt?:string };
const statusLabel:Record<string,string>={new:"Ontvangen",investigating:"Wordt onderzocht",fixed:"Opgelost",closed:"Afgesloten"};

export function SupportCenter(){
 const [reports,setReports]=useState<Report[]>([]),[loading,setLoading]=useState(true),[error,setError]=useState("");
 async function load(){setLoading(true);setError("");try{const result=await authenticatedRequest("/api/feedback") as {reports?:Report[]};setReports(Array.isArray(result.reports)?result.reports:[])}catch(cause){setError(cause instanceof Error?cause.message:"Meldingen konden niet worden geladen.")}finally{setLoading(false)}}
 useEffect(()=>{void load()},[]);
 return <section className="support-center"><header><div><span>SUPPORT EN TRADECONTROLE</span><h2>Mijn meldingen</h2><p>Hier zie je of een gemelde trade is ontvangen, onderzocht of opgelost en lees je het antwoord van TradeMentor.</p></div><button type="button" onClick={load} disabled={loading}>{loading?"Vernieuwen…":"Vernieuwen"}</button></header>{error?<p className="support-error">{error}</p>:loading?<div className="support-loading">Meldingen worden opgehaald…</div>:reports.length?<div className="support-report-list">{reports.map(report=><article key={report.id}><div><span>{new Date(report.createdAt||Date.now()).toLocaleString("nl-NL")}</span><em className={report.status}>{statusLabel[report.status]||report.status}</em></div><h3>{report.title}</h3><p>{report.description.split("\n\nAutomatisch meegestuurde")[0]}</p>{report.adminNote&&<blockquote><b>Antwoord TradeMentor</b>{report.adminNote}</blockquote>}</article>)}</div>:<div className="support-empty"><strong>Nog geen meldingen</strong><span>Gebruik het vraagteken bij een trade wanneer iets niet logisch lijkt.</span></div>}</section>;
}
