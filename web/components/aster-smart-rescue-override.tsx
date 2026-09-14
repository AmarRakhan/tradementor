"use client";

import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

type Level = { index:number; dropPercent:number; triggerPrice:number; orderMarginUsd:number; status:string };
type Current = {
  cycleId:string; dcaTotal:number; rescueRangePercent:number; filledCount:number; skippedCount:number; remainingCount:number;
  breakEvenNowPercent:number; maxAllocationUsd:number; actualMarginUsd:number; futurePlannedMarginUsd:number;
  orderGrowthMultiplier:number; extensionVersion:number;
  position:{ entryPrice:number; markPrice:number; quantity:number; leverage:number };
  levels:Level[];
};
type Payload = { symbol:string; pairLabel?:string; active:boolean; ordersSent:number; current:Current };
type PreviewRow = Level & { averageEntryPrice:number; breakEvenPrice:number; recoveryToBreakEvenPercent:number; isNew:boolean };

const money=(v:number)=>Number.isFinite(v)?`$${v<10?v.toFixed(2):v.toFixed(0)}`:"—";
const num=(raw:string)=>Number(raw.replace(",","."));
const finite=(v:unknown,fallback=0)=>Number.isFinite(Number(v))?Number(v):fallback;

function preview(current:Current,total:number,range:number,growth:number){
  const oldTotal=current.dcaTotal; const extra=Math.max(0,total-oldTotal); const oldRange=current.rescueRangePercent;
  const oldLevels=current.levels.map(row=>({...row})); const newLevels:Level[]=[];
  const lastMargin=finite(oldLevels.at(-1)?.orderMarginUsd);
  if(extra>0&&range>oldRange&&growth>=1&&lastMargin>0){
    for(let offset=1;offset<=extra;offset+=1){
      const fraction=offset/extra; const drop=offset===extra?range:oldRange+(range-oldRange)*Math.pow(fraction,1.5);
      newLevels.push({index:oldTotal+offset,dropPercent:drop,triggerPrice:100*(1-drop/100),orderMarginUsd:lastMargin*Math.pow(growth,offset),status:"PENDING"});
    }
  }
  const anchor=current.position.entryPrice>0?current.position.entryPrice:100;
  newLevels.forEach(row=>{row.triggerPrice=anchor*(1-row.dropPercent/100)});
  const future=[...oldLevels.filter(row=>row.status==="PENDING"||row.status==="ARMED"),...newLevels].sort((a,b)=>a.index-b.index);
  let qty=Math.max(0,current.position.quantity); let notional=qty*Math.max(0,current.position.entryPrice); const leverage=Math.max(1,current.position.leverage||1);
  const rows:PreviewRow[]=[];
  for(const row of future){
    const addNotional=row.orderMarginUsd*leverage; const addQty=row.triggerPrice>0?addNotional/row.triggerPrice:0;
    notional+=addNotional; qty+=addQty; const avg=qty>0?notional/qty:current.position.entryPrice;
    rows.push({...row,averageEntryPrice:avg,breakEvenPrice:avg,recoveryToBreakEvenPercent:row.triggerPrice>0?(avg/row.triggerPrice-1)*100:0,isNew:row.index>oldTotal});
  }
  const addedMargin=newLevels.reduce((s,row)=>s+row.orderMarginUsd,0); const deepest=rows.at(-1);
  return {newLevels,rows,addedMargin,maxAllocation:current.maxAllocationUsd+addedMargin,finalBreakEven:deepest?.breakEvenPrice??current.position.entryPrice,finalRecovery:deepest?.recoveryToBreakEvenPercent??current.breakEvenNowPercent};
}

function Chart({rows,current,breakEven,recovery}:{rows:PreviewRow[];current:number;breakEven:number;recovery:number}){
  const values=[current,breakEven,...rows.map(r=>r.triggerPrice)].filter(v=>Number.isFinite(v)&&v>0); const min=Math.min(...values)*.995,max=Math.max(...values)*1.005;
  const y=(p:number)=>132-((p-min)/Math.max(.0000001,max-min))*100; const pts=rows.map((r,i)=>`${22+(i/Math.max(1,rows.length-1))*265},${y(r.triggerPrice)}`).join(" ");
  return <svg viewBox="0 0 330 155" role="img" aria-label={`Nog ${recovery.toFixed(2)}% naar break-even`}>
    {pts&&<polyline points={pts} fill="none" stroke="#68aaff" strokeWidth="1.8"/>}
    {rows.map((r,i)=><circle key={`${r.index}-${i}`} cx={22+(i/Math.max(1,rows.length-1))*265} cy={y(r.triggerPrice)} r={r.isNew?3:2.2} fill={r.isNew?"#6fb4ff":"#365f80"}/>)}
    <line x1="14" y1={y(breakEven)} x2="316" y2={y(breakEven)} stroke="#35ebb2" strokeWidth="1.8" strokeDasharray="6 5"/>
    <text x="16" y={Math.max(10,y(breakEven)-5)} fill="#70f2c7" fontSize="8">BREAK-EVEN {breakEven.toFixed(4)}</text>
    <circle cx="278" cy={y(current)} r="5" fill="#ff7892"/><text x="286" y={y(current)+3} fill="#ff90a4" fontSize="8">NU {current.toFixed(4)}</text>
    <rect x="155" y="136" width="160" height="16" rx="8" fill="rgba(53,235,178,.12)"/><text x="235" y="147" textAnchor="middle" fill="#8ff6d2" fontSize="8" fontWeight="700">Nog +{Math.max(0,recovery).toFixed(2)}% naar break-even</text>
  </svg>;
}

export function AsterSmartRescueOverride({symbol,onClose}:{symbol:string;onClose:()=>void}){
  const [data,setData]=useState<Payload|null>(null); const [busy,setBusy]=useState(false); const [message,setMessage]=useState("");
  const [total,setTotal]=useState(""); const [range,setRange]=useState(""); const [growth,setGrowth]=useState(""); const [loadedCycle,setLoadedCycle]=useState("");
  async function load(){
    setBusy(true);setMessage("");
    try{const result=await authenticatedRequest(`/api/exchanges/aster/strategy2/smart-rescue/${encodeURIComponent(symbol)}`,{cache:"no-store"}) as Payload;
      setData(result);setLoadedCycle(result.current.cycleId);setTotal(String(result.current.dcaTotal));setRange(String(result.current.rescueRangePercent));setGrowth(String(result.current.orderGrowthMultiplier||1));
    }catch(error){setMessage(error instanceof Error?error.message:"Actieve Smart Rescue-cycle kon niet worden geladen.");}
    finally{setBusy(false);}
  }
  useEffect(()=>{void load();},[symbol]);
  const proposedTotal=Math.round(num(total)||0),proposedRange=num(range),proposedGrowth=num(growth);
  const local=useMemo(()=>data?preview(data.current,proposedTotal,proposedRange,proposedGrowth):null,[data,proposedTotal,proposedRange,proposedGrowth]);
  const current=data?.current; const pair=data?.pairLabel||`${symbol.replace(/USDT$/i,"")}/USDT`; const extra=current?proposedTotal-current.dcaTotal:0;
  const validation=!current?"":proposedTotal<=current.dcaTotal?`Nieuw totaal moet groter zijn dan ${current.dcaTotal}.`:proposedTotal>500?"Nieuw totaal mag maximaal 500 DCA’s zijn.":!(proposedRange>current.rescueRangePercent&&proposedRange<100)?`Nieuw rescue bereik moet dieper zijn dan ${current.rescueRangePercent.toFixed(2)}%.`:!(proposedGrowth>=1)?"Ordergroei moet minimaal 1,00× zijn.":"";
  async function save(){
    if(!current||validation||busy)return;setBusy(true);setMessage("");
    try{const result=await authenticatedRequest(`/api/exchanges/aster/strategy2/smart-rescue/${encodeURIComponent(symbol)}/extend`,{method:"PUT",body:JSON.stringify({cycleId:loadedCycle,newTotalDca:proposedTotal,newRescueRangePercent:proposedRange,futureGrowthMultiplier:proposedGrowth})}) as Payload;
      setData(result);setLoadedCycle(result.current.cycleId);setMessage(`Uitbreiding opgeslagen: ${result.current.dcaTotal} DCA’s. Er is geen order geplaatst.`);setTotal(String(result.current.dcaTotal));setRange(String(result.current.rescueRangePercent));setGrowth(String(result.current.orderGrowthMultiplier));
    }catch(error){setMessage(error instanceof Error?error.message:"Uitbreiding opslaan is mislukt.");}
    finally{setBusy(false);}
  }
  return <div className="sro-backdrop" role="dialog" aria-modal="true" aria-label={`${pair} Smart Rescue Override`}>
    <section className="sro-modal">
      <header className="sro-head"><div><small>SMART RESCUE OVERRIDE</small><h2>{pair} · actieve Smart Rescue-cycle</h2><p>Deze trade draait al met Smart Rescue. Bestaande fills blijven ongewijzigd; je voegt alleen extra toekomstige rescue-stappen toe.</p></div><button type="button" aria-label="Sluiten" onClick={onClose}>×</button></header>
      {!current?<div className="sro-loading">{busy?"Smart Rescue-cycle laden…":message||"Geen actieve Smart Rescue-cycle gevonden."}</div>:<>
        <section className="sro-panel"><h3>Huidige Smart Rescue status</h3><div className="sro-stats"><article><small>Huidige ladder</small><b>{current.dcaTotal} DCA’s</b><span>over {current.rescueRangePercent.toFixed(2)}%</span></article><article><small>Gevuld</small><b>{current.filledCount}</b><span>van {current.dcaTotal}</span></article><article><small>Nog beschikbaar</small><b>{current.remainingCount}</b><span>DCA’s</span></article><article><small>Break-even vanaf nu</small><b className="green">{current.breakEvenNowPercent>=0?"+":""}{current.breakEvenNowPercent.toFixed(2)}%</b></article><article><small>Max inzet / munt</small><b>{money(current.maxAllocationUsd)}</b></article></div></section>
        <section className="sro-panel"><h3 className="green">Ladder uitbreiden</h3><p className="muted">Alleen toekomstige stappen worden toegevoegd. Bestaande FILLED, SKIPPED en ARMED state blijft exact staan.</p><div className="sro-fields"><label>Nieuw totaal DCA’s<input inputMode="numeric" value={total} onChange={e=>setTotal(e.target.value.replace(/[^0-9]/g,""))}/></label><label>Nieuw rescue bereik<span><input inputMode="decimal" value={range} onChange={e=>setRange(e.target.value.replace(",","."))}/><b>%</b></span></label><label>Ordergroei vanaf volgende stap<span><input inputMode="decimal" value={growth} onChange={e=>setGrowth(e.target.value.replace(",","."))}/><b>×</b></span></label></div>{validation&&<p className="sro-error">{validation}</p>}</section>
        {local&&<section className="sro-panel"><h3 className="green">Preview uitbreiding</h3><div className="sro-preview"><div><span>Huidige ladder: <b>{current.dcaTotal}</b> → Nieuw totaal: <b className="green">{proposedTotal||"—"}</b></span><span>Toe te voegen steps: <b className="green">+{Math.max(0,extra)}</b></span><span>Laatste nieuwe DCA: <b className="green">-{Number.isFinite(proposedRange)?proposedRange.toFixed(2):"—"}%</b></span></div><div><span>Nieuwe max inzet / munt:</span><b className="green big">{money(local.maxAllocation)}</b><span>Nieuwe break-even diepste stap:</span><b className="green big">+{Math.max(0,local.finalRecovery).toFixed(2)}%</b></div></div><div className="sro-chart"><Chart rows={local.rows} current={current.position.markPrice} breakEven={local.finalBreakEven} recovery={local.finalRecovery}/></div></section>}
        <div className="sro-warning"><b>⚠ Waarschuwing</b><span>Deze uitbreiding verhoogt alleen toekomstige Smart Rescue-stappen. Reeds gevulde of overgeslagen stappen veranderen niet. Opslaan plaatst geen order.</span></div>
        {message&&<p className={/mislukt|geen actieve|moet|niet meer/i.test(message)?"sro-message error":"sro-message"}>{message}</p>}
        <footer className="sro-actions"><button type="button" onClick={onClose}>Annuleren</button><button type="button" disabled={busy||!!validation||extra<=0} onClick={save}>{busy?"Opslaan…":"Uitbreiding opslaan"}</button></footer>
        <details className="sro-details"><summary>Bekijk volledige ladder <span>›</span></summary><div>{current.levels.map(row=><p key={row.index}><b>DCA {row.index}</b><span>-{row.dropPercent.toFixed(3)}% · {row.status}</span><span>{money(row.orderMarginUsd)}</span></p>)}{local?.newLevels.map(row=><p key={`new-${row.index}`} className="new"><b>DCA {row.index}</b><span>-{row.dropPercent.toFixed(3)}% · NIEUW</span><span>{money(row.orderMarginUsd)}</span></p>)}</div></details>
      </>}
      <style>{`
        .sro-backdrop{position:fixed;inset:0;z-index:10045;background:rgba(0,0,0,.82);backdrop-filter:blur(9px);display:flex;align-items:flex-end;justify-content:center;padding-top:max(12px,env(safe-area-inset-top))}.sro-modal{width:min(100%,704px);max-height:94dvh;overflow:auto;border:1px solid rgba(45,238,168,.58);border-radius:24px 24px 0 0;background:radial-gradient(circle at 82% 5%,rgba(29,225,153,.09),transparent 28%),linear-gradient(180deg,#06110d,#020705);color:#f5f8f6;padding:18px 16px calc(22px + env(safe-area-inset-bottom));box-shadow:0 -22px 70px rgba(0,0,0,.6)}
        .sro-head{display:flex;gap:12px;justify-content:space-between}.sro-head small{color:#53f0b2;letter-spacing:.16em;font-weight:900}.sro-head h2{font-size:20px;margin:5px 0}.sro-head p{margin:0;color:#a8b5af;font-size:12px;line-height:1.45;max-width:560px}.sro-head>button{flex:0 0 43px;width:43px;height:43px;border-radius:14px;border:1px solid #405047;background:#26332d;color:#fff;font-size:27px}.sro-panel{margin-top:12px;padding:13px;border:1px solid rgba(66,222,160,.32);border-radius:15px;background:rgba(2,12,8,.74)}.sro-panel h3{margin:0 0 8px;font-size:16px}.green{color:#39e8a6!important}.muted{color:#91a099;font-size:11px;margin:0 0 10px}.sro-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.sro-stats article{min-height:72px;padding:9px;border:1px solid rgba(76,213,158,.24);border-radius:11px;background:rgba(8,23,17,.68);display:grid;align-content:center}.sro-stats article:nth-child(4),.sro-stats article:nth-child(5){grid-column:span 1}.sro-stats small,.sro-stats span{color:#8f9e97;font-size:10px}.sro-stats b{font-size:17px;margin:2px 0}.sro-fields{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.sro-fields label{display:grid;gap:5px;color:#b9c5bf;font-size:11px}.sro-fields label>input,.sro-fields label>span{height:48px;border:1px solid #304039;border-radius:10px;background:#111a16;color:#fff;display:flex;align-items:center}.sro-fields input{width:100%;min-width:0;height:100%;padding:0 11px;border:0;outline:0;background:transparent;color:#fff;font-size:17px}.sro-fields b{padding-right:10px;color:#9aa8a1}.sro-error{margin:8px 0 0;color:#ff9a78;font-size:11px}.sro-preview{display:grid;grid-template-columns:1.4fr 1fr;gap:12px}.sro-preview>div{display:grid;gap:6px;border-right:1px solid rgba(255,255,255,.10);padding-right:10px}.sro-preview>div:last-child{border-right:0}.sro-preview span{font-size:11px;color:#a9b4af}.big{font-size:17px}.sro-chart{margin-top:10px;border:1px solid rgba(45,238,168,.23);border-radius:12px;background:#020806;padding:5px;overflow:hidden}.sro-chart svg{display:block;width:100%;height:auto}.sro-warning{margin-top:12px;padding:11px 13px;border:1px solid #d39723;border-radius:13px;background:linear-gradient(90deg,rgba(148,89,7,.22),rgba(50,27,3,.30));display:grid;grid-template-columns:auto 1fr;gap:4px 10px}.sro-warning b{color:#f7b849}.sro-warning span{color:#d3c3aa;font-size:11px;line-height:1.4}.sro-message{padding:9px;border-radius:9px;background:rgba(45,238,168,.09);color:#8af1c4;font-size:12px}.sro-message.error{background:rgba(255,110,130,.08);color:#ff9eaa}.sro-actions{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px}.sro-actions button{min-height:51px;border-radius:13px;font-weight:900;font-size:14px;border:1px solid #53635b;background:#101a16;color:#e5ece8}.sro-actions button:last-child{background:linear-gradient(180deg,#31eaa6,#20ce8f);border-color:#43f2b1;color:#03130c;box-shadow:0 0 22px rgba(49,234,166,.18)}.sro-actions button:disabled{opacity:.45}.sro-details{margin-top:10px}.sro-details summary{cursor:pointer;text-align:center;color:#bdc8c3;font-size:12px;padding:8px}.sro-details summary span{color:#32e8a5;font-size:18px;margin-left:6px}.sro-details>div{border:1px solid #203129;border-radius:10px;overflow:hidden}.sro-details p{display:grid;grid-template-columns:80px 1fr auto;gap:8px;margin:0;padding:7px 9px;border-bottom:1px solid rgba(255,255,255,.04);font-size:10px}.sro-details p.new{background:rgba(49,234,166,.04)}.sro-details p span{color:#8fa098}.sro-loading{margin-top:15px;padding:14px;border:1px solid #24352d;border-radius:12px;color:#aab7b1}
        @media(max-width:480px){.sro-modal{padding:15px 12px calc(18px + env(safe-area-inset-bottom));border-radius:20px 20px 0 0}.sro-head h2{font-size:18px}.sro-stats{grid-template-columns:1fr 1fr}.sro-stats article:nth-child(5){grid-column:1/-1}.sro-fields{grid-template-columns:1fr}.sro-preview{grid-template-columns:1fr}.sro-preview>div{border-right:0;border-bottom:1px solid rgba(255,255,255,.08);padding:0 0 8px}.sro-preview>div:last-child{border-bottom:0}.sro-actions{position:sticky;bottom:-1px;background:linear-gradient(180deg,transparent,#020705 22%);padding-top:18px}.sro-warning{grid-template-columns:1fr}.sro-details p{grid-template-columns:60px 1fr auto}}
      `}</style>
    </section>
  </div>;
}

// Visual reference: file_000000005a14820a846ec59dfd9fc5a1 (smart_rescue_override_dashboard.png)
