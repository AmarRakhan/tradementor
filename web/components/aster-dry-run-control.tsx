"use client";

import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { AsterUniverseStatus } from "@/components/aster-universe-status";

type Fields = {
  mode: "paper" | "live"; base: string; pairs: string; topN: string;
  longDca: string; shortDca: string; maxLongDca: string; maxShortDca: string;
  dcaMultiplier: string; takeProfit: string; botBudget: string; pairTolerance: string;
  reinvest: string; blockRisk: string; reduceRisk: string; emergencyRisk: string;
};
const defaults: Fields = { mode:"paper",base:"10",pairs:"5",topN:"50",longDca:"2",shortDca:"5",
  maxLongDca:"3",maxShortDca:"3",dcaMultiplier:"1",takeProfit:"0.5",botBudget:"50",
  pairTolerance:"5",reinvest:"50",blockRisk:"50",reduceRisk:"70",emergencyRisk:"80" };
const n=(v:string,f=0)=>Number.isFinite(Number(v))?Number(v):f;

export function AsterDryRunControl({ snapshot=null, onChanged=()=>{} }:{snapshot?:Record<string,unknown>|null;onChanged?:()=>void}) {
  const [fields,setFields]=useState(defaults); const [open,setOpen]=useState(false);
  const [busy,setBusy]=useState(false); const [message,setMessage]=useState("");
  const [confirmStart,setConfirmStart]=useState(false); const [confirmClose,setConfirmClose]=useState(false);
  const [tone,setTone]=useState<"ok"|"warn"|"error">("warn");
  useEffect(()=>{ if(open)return; const raw=snapshot?.automationSettings; if(!raw||typeof raw!=="object")return;
    const s=raw as Record<string,unknown>; const pct=(k:string,d:number)=>String(Number(s[k]??d)*100);
    setFields({mode:s.mode==="live"?"live":"paper",base:String(s.baseNotional??10),pairs:String(s.maximumPairs??5),
      topN:String(s.universeTopN??50),longDca:pct("longDcaDeviation",.02),shortDca:pct("shortDcaDeviation",.05),
      maxLongDca:String(s.maximumLongDca??3),maxShortDca:String(s.maximumShortDca??3),dcaMultiplier:String(s.dcaMultiplier??1),
      takeProfit:pct("netTakeProfit",.005),botBudget:pct("botMarginBudgetRatio",.5),pairTolerance:pct("pairBudgetTolerance",.05),
      reinvest:pct("momentumReinvestRatio",.5),blockRisk:pct("blockRiskRatio",.5),reduceRisk:pct("reduceRiskRatio",.7),emergencyRisk:pct("emergencyRiskRatio",.8)});
  },[snapshot?.automationSettings,open]);
  const settings=useMemo(()=>({enabled:false,mode:fields.mode,baseNotional:n(fields.base),maximumPairs:Math.round(n(fields.pairs)),
    universeTopN:n(fields.topN),scanIntervalSeconds:60,longDcaDeviation:n(fields.longDca)/100,
    shortDcaDeviation:n(fields.shortDca)/100,maximumLongDca:Math.round(n(fields.maxLongDca)),maximumShortDca:Math.round(n(fields.maxShortDca)),
    dcaMultiplier:n(fields.dcaMultiplier),netTakeProfit:n(fields.takeProfit)/100,botMarginBudgetRatio:n(fields.botBudget)/100,
    pairBudgetTolerance:n(fields.pairTolerance)/100,momentumReinvestRatio:n(fields.reinvest)/100,blockRiskRatio:n(fields.blockRisk)/100,
    reduceRiskRatio:n(fields.reduceRisk)/100,emergencyRiskRatio:n(fields.emergencyRisk)/100,dailyNewPairPause:.05,marginMode:"cross",useMaximumLeverage:true}),[fields]);
  async function act(kind:"save"|"simulate"|"start"|"stop") { setBusy(true);setMessage(""); try{
    const path=kind==="save"?"settings":kind; const method=kind==="save"?"PUT":"POST";
    const body=kind==="stop"?{confirm:true}:kind==="start"?{confirm:true,settings}:{settings:{...settings,mode:kind==="simulate"?"paper":settings.mode}};
    const result=await authenticatedRequest(`/api/exchanges/aster/automation/${path}`,{method,body:JSON.stringify(body)}) as Record<string,unknown>;
    setTone("ok"); setMessage(kind==="simulate"?`Simulatie geslaagd: ${String(result.plannedPositions||0)} posities gepland, 0 verzonden.`:
      kind==="start"?"Live monitoring gestart. Orders worden per LONG/SHORT-paar bevestigd.":kind==="stop"?"Veilig gestopt; bescherming blijft actief.":"Persoonlijke Aster-instellingen opgeslagen."); onChanged();
  }catch(e){setTone("error");setMessage(e instanceof Error?e.message:"Opdracht mislukt.");}finally{setBusy(false)} }
  const active=Boolean(snapshot?.automationEnabled);
  async function closeAll(){setBusy(true);setMessage("");try{const r=await authenticatedRequest("/api/exchanges/aster/automation/close-all",{method:"POST",body:JSON.stringify({confirm:true})}) as Record<string,unknown>;setTone("warn");setMessage(String(r.message||"Alle posities worden gesloten en gecontroleerd."));setConfirmClose(false);onChanged();}catch(e){setTone("error");setMessage(e instanceof Error?e.message:"Alles sluiten is mislukt.");}finally{setBusy(false)}}
  return <article className="strategy-card strategy-control-card">
    <div className="strategy-title-row"><div><span className="kicker">ASTER MULTI-PAIR</span><h2>Profit Harvest Hedge</h2></div><span className={`strategy-state ${active?"on":""}`}>{active?"ACTIEF":"GESTOPT"}</span></div>
    <p>$10 LONG + $10 SHORT per pair · DCA 2%/5% · netto oogst 0,5% · Cross · maximale contractleverage.</p>
    <div className="strategy-facts"><span>{fields.pairs} pairs</span><span>Top {fields.topN}</span><span>Elke minuut</span><span>{fields.mode.toUpperCase()}</span></div>
    <AsterUniverseStatus value={snapshot?.automationUniverse}/>
    <button type="button" className="expand-settings" onClick={()=>setOpen(!open)}>{open?"Instellingen sluiten":"Strategie instellen"}</button>
    {open&&<div className="strategy-settings">
      <div className="mode-switch"><button className={fields.mode==="paper"?"active":""} onClick={()=>setFields({...fields,mode:"paper"})}>Paper</button><button className={fields.mode==="live"?"active danger":""} onClick={()=>setFields({...fields,mode:"live"})}>Echt geld</button></div>
      <div className="settings-grid">
        <F l="Positieomvang per kant (USD)" v={fields.base} c={v=>setFields({...fields,base:v})}/><F l="Max. actieve pairs" v={fields.pairs} c={v=>setFields({...fields,pairs:v})}/>
        <TopNField v={fields.topN} c={v=>setFields({...fields,topN:v})}/><F l="Netto winstoogst (%)" v={fields.takeProfit} c={v=>setFields({...fields,takeProfit:v})}/>
        <F l="LONG DCA-afstand (%)" v={fields.longDca} c={v=>setFields({...fields,longDca:v})}/><F l="SHORT DCA-afstand (%)" v={fields.shortDca} c={v=>setFields({...fields,shortDca:v})}/>
        <F l="Max. LONG DCA" v={fields.maxLongDca} c={v=>setFields({...fields,maxLongDca:v})}/><F l="Max. SHORT DCA" v={fields.maxShortDca} c={v=>setFields({...fields,maxShortDca:v})}/>
        <F l="DCA-vermenigvuldiger" v={fields.dcaMultiplier} c={v=>setFields({...fields,dcaMultiplier:v})}/><F l="Botbudget (% portfolio)" v={fields.botBudget} c={v=>setFields({...fields,botBudget:v})}/>
        <F l="Pairspeling (%)" v={fields.pairTolerance} c={v=>setFields({...fields,pairTolerance:v})}/><F l="Winst herinvesteren (%)" v={fields.reinvest} c={v=>setFields({...fields,reinvest:v})}/>
        <F l="Nieuwe risico's blokkeren (%)" v={fields.blockRisk} c={v=>setFields({...fields,blockRisk:v})}/><F l="Risico verlagen (%)" v={fields.reduceRisk} c={v=>setFields({...fields,reduceRisk:v})}/><F l="Noodrem (%)" v={fields.emergencyRisk} c={v=>setFields({...fields,emergencyRisk:v})}/>
      </div>
      <p className="inline-warning">Live start opent marktorders met echt geld. Alles sluiten blijft dubbel bevestigd en apart vergrendeld.</p>
      <div className="strategy-actions"><button disabled={busy} onClick={()=>act("save")}>Opslaan</button><button disabled={busy} onClick={()=>act("simulate")}>Veilig simuleren</button>{active?<button className="stop-action" disabled={busy} onClick={()=>act("stop")}>Veilig stoppen</button>:<button className="start-action" disabled={busy||fields.mode!=="live"} onClick={()=>setConfirmStart(true)}>Live bot starten</button>}<button className="stop-action" disabled={busy} onClick={()=>setConfirmClose(true)}>Alles sluiten</button></div>
      {confirmStart&&<div className="confirmation-panel"><strong>Echt geld bevestigen</strong><p>Open maximaal {fields.pairs} pairs met $ {fields.base} LONG én $ {fields.base} SHORT per pair. Marketorders, Cross Margin en maximale contractleverage.</p><div className="strategy-actions"><button onClick={()=>setConfirmStart(false)}>Annuleren</button><button className="start-action" disabled={busy} onClick={()=>{setConfirmStart(false);act("start")}}>Bevestig en start live</button></div></div>}
      {confirmClose&&<div className="confirmation-panel"><strong>Alle Aster-posities sluiten?</strong><p>Dit realiseert ook open verliezen. De opdracht kan na verzending niet worden teruggedraaid.</p><div className="strategy-actions"><button onClick={()=>setConfirmClose(false)}>Annuleren</button><button className="stop-action" disabled={busy} onClick={closeAll}>Ja, sluit alles</button></div></div>}
    </div>}{message&&<p className={`strategy-message ${tone}`}>{message}</p>}
  </article>;
}
function F({l,v,c}:{l:string;v:string;c:(v:string)=>void}){return <label>{l}<input inputMode="decimal" value={v} onChange={e=>c(e.target.value.replace(",","."))}/></label>}
function TopNField({v,c}:{v:string;c:(v:string)=>void}){return <label>Aster USDT-handelsuniversum – Top-N op volume en liquiditeit<input type="number" inputMode="numeric" min="1" step="1" value={v} onChange={e=>c(e.target.value)}/></label>}
