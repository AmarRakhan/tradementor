"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { firebaseAuth } from "@/lib/firebase";
import { WEBAPP_BUILD_NUMBER } from "@/lib/app-version";
import {
  readTradeHistoryCache, writeTradeHistoryCache, tradeHistoryFileName, tradeHistoryFileContent,
  syncProgressLabel, tradeRowKey, SYNC_STEP_PAUSE_MS, SYNC_RETRY_PAUSE_MS, SYNC_MAX_STEPS,
  type TradeJournalSyncResult,
} from "@/lib/trade-journal.mjs";

// Build 648: the card shows the remembered list at once, refreshes in the background from the trade journal,
// and the download button under × exports the full closed history (with settings) as a JSON file.

type Trade = Record<string, unknown>;
type Mode = "all" | "today";
type Source = "journal" | "legacy";
const asNumber = (v:unknown) => v == null || v === "" || !Number.isFinite(Number(v)) ? null : Number(v);
const asDate = (v:unknown) => { const t= typeof v === "number" ? (v < 1e10 ? v*1000 : v) : Date.parse(String(v||"")); return Number.isFinite(t)&&t>0?t:null; };
const dateKey = (t:number) => {const parts=new Intl.DateTimeFormat("en-GB",{timeZone:"Europe/Amsterdam",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(t); const pick=(key:string)=>parts.find(p=>p.type===key)?.value||"";return `${pick("year")}-${pick("month")}-${pick("day")}`;};
const formatted = (n:number|null) => n===null?"—":new Intl.NumberFormat("nl-NL",{minimumFractionDigits:2,maximumFractionDigits:2}).format(Math.abs(n));
const duration = (row:Trade) => {const opened=asDate(row.openedAt),closed=asDate(row.closedAt);if(opened===null||closed===null||closed<opened)return "—";const mins=Math.floor((closed-opened)/60000);return mins>=1440?`${Math.floor(mins/1440)}d ${Math.floor(mins%1440/60)}u`:mins>=60?`${Math.floor(mins/60)}u ${mins%60}m`:`${mins}m`;};
const sleep = (ms:number, signal:AbortSignal) => new Promise<void>((resolve) => { const t = window.setTimeout(resolve, ms); signal.addEventListener("abort", () => { window.clearTimeout(t); resolve(); }, { once: true }); });
const storage = () => { try { return typeof window === "undefined" ? null : window.localStorage; } catch { return null; } };

function uniqueSorted(source: Trade[]): Trade[] {
  const unique = new Map<string, Trade>();
  source.forEach((trade, index) => { if (trade && typeof trade === "object") { const key = tradeRowKey(trade, index); if (!unique.has(key)) unique.set(key, trade); } });
  return [...unique.values()].sort((a,b)=>(asDate(b.closedAt)??0)-(asDate(a.closedAt)??0));
}

/** One sync step; null on a temporary refusal (busy, too soon, budget) so the caller simply waits and retries. */
async function syncStep(): Promise<TradeJournalSyncResult | null> {
  try {
    return await authenticatedRequest("/api/exchanges/aster/trade-journal/sync", { method: "POST", body: "{}", cache: "no-store" }) as TradeJournalSyncResult;
  } catch (error) {
    const text = error instanceof Error ? error.message : "";
    if (/wachten|al bijgewerkt|budget|HTTP 429/i.test(text)) return null;
    throw error;
  }
}

export function ClosedTradesFlip({mode,onClose,todayCount}:{mode:Mode;onClose:()=>void;todayCount:string}) {
 const uid = firebaseAuth.currentUser?.uid || "";
 const cached = useMemo(() => readTradeHistoryCache(storage(), uid), [uid]);
 const [rows,setRows]=useState<Trade[]>(cached?.rows || []);
 const [source,setSource]=useState<Source>(cached?.source || "legacy");
 const [busy,setBusy]=useState(!cached),[error,setError]=useState(""),[refreshing,setRefreshing]=useState(true);
 const [building,setBuilding]=useState("");
 const [download,setDownload]=useState<{busy:boolean;label:string;error:string}>({busy:false,label:"",error:""});
 const [visible,setVisible]=useState(20),[flipped,setFlipped]=useState(false);
 const alive = useRef(new AbortController());

 const show = useCallback((next: Trade[], from: Source) => {
   const sorted = uniqueSorted(next);
   setRows(sorted); setSource(from); setBusy(false); setError("");
   writeTradeHistoryCache(storage(), firebaseAuth.currentUser?.uid || uid, sorted, from);
 }, [uid]);

 const loadJournal = useCallback(async () => {
   const data = await authenticatedRequest("/api/exchanges/aster/trade-journal/recent?limit=300", { cache: "no-store" });
   return { rows: Array.isArray(data?.rows) ? data.rows as Trade[] : [], ready: data?.backfillComplete === true };
 }, []);

 const loadLegacy = useCallback(async () => {
   const data = await authenticatedRequest("/api/exchanges/aster/closed-trades", { cache: "no-store" });
   return Array.isArray(data?.closedTrades) ? data.closedTrades as Trade[] : [];
 }, []);

 /** Repeat sync steps until the journal is complete; report progress. Stops when the card closes. */
 const runSync = useCallback(async (onProgress: (result: TradeJournalSyncResult) => void, signal: AbortSignal) => {
   let failures = 0;
   for (let step = 0; step < SYNC_MAX_STEPS && !signal.aborted; step += 1) {
     let result: TradeJournalSyncResult | null = null;
     try { result = await syncStep(); failures = 0; }
     catch (exc) { failures += 1; if (failures >= 3) throw exc; }
     if (signal.aborted) return null;
     if (result) { onProgress(result); if (result.complete) return result; }
     await sleep(result && !result.rateLimited ? SYNC_STEP_PAUSE_MS : SYNC_RETRY_PAUSE_MS, signal);
   }
   return null;
 }, []);

 useEffect(()=>{
   const controller = new AbortController(); alive.current = controller; setFlipped(true);
   (async () => {
     // 1) the journal (fast, Firestore only) — or the old list while the journal is still being built
     let ready = false;
     try {
       const journal = await loadJournal();
       ready = journal.ready;
       if (controller.signal.aborted) return;
       if (ready) show(journal.rows, "journal");
     } catch { /* the old list below still works */ }
     if (!ready) {
       try { const legacy = await loadLegacy(); if (!controller.signal.aborted) show(legacy, "legacy"); }
       catch (e) { if (!controller.signal.aborted && !readTradeHistoryCache(storage(), uid)) { setError(e instanceof Error ? e.message : "Historie tijdelijk niet beschikbaar"); setBusy(false); } }
     }
     // 2) bring the journal up to date in the background, then show it
     try {
       await runSync((result) => {
         if (!result.backfillComplete) setBuilding(`Volledige historie opbouwen… ${Math.round(Number(result.progress?.percent) || 0)}%`);
         else setBuilding("");
       }, controller.signal);
       if (controller.signal.aborted) return;
       const journal = await loadJournal();
       if (!controller.signal.aborted && journal.ready) { show(journal.rows, "journal"); setBuilding(""); }
     } catch { /* keep what is on screen; a later open continues where this stopped */ }
     finally { if (!controller.signal.aborted) setRefreshing(false); }
   })();
   return () => controller.abort();
 },[loadJournal,loadLegacy,runSync,show,uid]);

 useEffect(()=>{const old=document.body.style.overflow;document.body.style.overflow="hidden";const key=(e:KeyboardEvent)=>{if(e.key==="Escape")onClose()};window.addEventListener("keydown",key);return()=>{document.body.style.overflow=old;window.removeEventListener("keydown",key)}},[onClose]);

 const startDownload = useCallback(async () => {
   if (download.busy) return;
   const signal = alive.current.signal;
   setDownload({ busy: true, label: "Historie bijwerken…", error: "" });
   try {
     const done = await runSync((result) => setDownload((d) => ({ ...d, label: syncProgressLabel(result) })), signal);
     if (signal.aborted) return;
     if (!done) throw new Error("De volledige historie is nog niet klaar. Probeer het zo nog eens; hij gaat verder waar hij was.");
     setDownload((d) => ({ ...d, label: "Bestand maken…" }));
     const payload = await authenticatedRequest("/api/exchanges/aster/trade-journal/export", { cache: "no-store" });
     if (signal.aborted) return;
     const blob = new Blob([tradeHistoryFileContent(payload, WEBAPP_BUILD_NUMBER)], { type: "application/json" });
     const name = tradeHistoryFileName(new Date());
     const file = typeof File === "function" ? new File([blob], name, { type: "application/json" }) : null;
     const nav = navigator as Navigator & { canShare?: (data: { files: File[] }) => boolean };
     const touch = typeof window.matchMedia === "function" && window.matchMedia("(pointer: coarse)").matches;
     if (touch && file && nav.canShare?.({ files: [file] }) && typeof nav.share === "function") {
       try { await nav.share({ files: [file], title: "Trade historie" }); setDownload({ busy: false, label: "", error: "" }); return; }
       catch (exc) { if (exc instanceof DOMException && exc.name === "AbortError") { setDownload({ busy: false, label: "", error: "" }); return; } }
     }
     const url = URL.createObjectURL(blob);
     const link = document.createElement("a");
     link.href = url; link.download = name; link.rel = "noopener"; document.body.appendChild(link); link.click(); link.remove();
     window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
     setDownload({ busy: false, label: "", error: "" });
   } catch (exc) {
     if (!signal.aborted) setDownload({ busy: false, label: "", error: exc instanceof Error ? exc.message : "Download mislukt" });
   }
 }, [download.busy, runSync]);

 const filtered=useMemo(()=>mode==="all"?rows:rows.filter(row=>{const t=asDate(row.closedAt);return t!==null&&dateKey(t)===dateKey(Date.now())}),[mode,rows]);
 const displayed=filtered.slice(0,visible);
 return <div className="aps-closed-overlay" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}>
  <div className="aps-closed-perspective"><section className={`aps-closed-flip ${flipped?"is-flipped":""}`} role="dialog" aria-modal="true" aria-label={mode==="all"?"Gesloten resultaat":"Trades gesloten vandaag"}>
  <div className="aps-closed-face aps-closed-front" aria-hidden="true"><strong>✦ AMAR CRYPTO BOT</strong></div>
  <div className="aps-closed-face aps-closed-back">
   <header><div><small>✦ TRADE HISTORIE</small><h2>{mode==="all"?"Gesloten resultaat":"Trades gesloten vandaag"}</h2><p>Nieuwste eerst · {source==="journal"?"tradejournaal":"bestaande Aster-gegevens"}{refreshing&&!busy?" · bijwerken…":""}</p></div>
    <div className="aps-closed-actions">
     <button type="button" onClick={onClose} aria-label="Terug">×</button>
     <button type="button" className="aps-closed-download" onClick={startDownload} disabled={download.busy} aria-label="Download alle gesloten trades" title="Download alle gesloten trades (JSON)" data-trade-history-download>
      <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M12 3v12m0 0-5-5m5 5 5-5M5 20h14" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/></svg>
     </button>
    </div>
   </header>
   {download.busy||download.error?<p role="status" className={`aps-closed-download-status${download.error?" is-error":""}`}>{download.error||download.label}</p>:null}
   {mode==="today"&&todayCount!=="—"?<p className="aps-closed-message">Gesloten volgens dagoverzicht: {todayCount}. Getoonde records zijn uitsluitend de beschikbare historische sluitingen.</p>:null}
   <div className="aps-closed-scroll">
    {busy?<p role="status" className="aps-closed-message">Trades laden…</p>:null}
    {error?<p role="alert" className="aps-closed-message">{error}</p>:null}
    {building&&!download.busy?<p role="status" className="aps-closed-building">{building}</p>:null}
    {!busy&&!error&&filtered.length===0?<p className="aps-closed-message">Geen beschikbare gesloten trades.</p>:null}
    {displayed.map((row,index)=>{const profit=asNumber(row.realizedPnlUsd);const margin=asNumber(row.marginUsd)??asNumber(row.executedMarginUsd)??asNumber(row.initialMarginUsd);const t=asDate(row.closedAt);const reason=typeof row.closeReason==="string"?row.closeReason:"";const partial=row.closeType==="PARTIAL";return <article className="aps-closed-row" key={tradeRowKey(row,index)}>
     <div className="aps-closed-row-head"><strong>{String(row.symbol||"—")}</strong><b className={row.side==="SHORT"?"short":"long"}>{String(row.side||"—")}</b><time>{t===null?"—":new Intl.DateTimeFormat("nl-NL",{timeZone:"Europe/Amsterdam",day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit"}).format(t)}</time></div>
     {reason?<p className="aps-closed-reason">{reason}{partial?" · deel gesloten":""}</p>:null}
     <div className="aps-closed-row-grid"><span><small>Resultaat</small><strong className={profit===null?"":profit>=0?"positive":"negative"}>{profit===null?"—":`${profit>=0?"+":"−"}US$ ${formatted(profit)}`}</strong></span><span><small>Marge</small><strong>{margin===null?"—":`US$ ${formatted(margin)}`}</strong></span><span><small>Duur</small><strong>{duration(row)}</strong></span></div>
    </article>})}
    {visible<filtered.length?<button type="button" className="aps-closed-more" onClick={()=>setVisible(n=>n+20)}>Meer laden</button>:null}
   </div>
   <footer>Alleen beschikbare gegevens · ontbrekende velden worden niet geschat</footer>
  </div></section></div>
 </div>;
}
