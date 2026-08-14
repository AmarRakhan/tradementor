function stamp(value:unknown){
 if(!value)return "—";
 const parsed=new Date(String(value));
 return Number.isNaN(parsed.getTime())?String(value):parsed.toLocaleString("nl-NL");
}

export function AsterUniverseStatus({value,label=""}:{value:unknown;label?:string}){
 const data=(value&&typeof value==="object"?value:{}) as Record<string,unknown>;
 const requested=Number(data.requestedTopN||0),eligible=Number(data.eligibleMarketCount||0),selected=Number(data.selectedMarketCount||0);
 if(!requested&&!eligible&&!selected)return <div className="strategy-message warn"><b>{label?`${label} · `:""}Aster USDT-perpetualuniversum</b><br/>Nog niet server-side ververst. Alleen nieuwe instappen blijven geblokkeerd.</div>;
 return <div className={`strategy-message ${data.entryBlocked===true?"warn":"ok"}`}>
  <b>{label?`${label} · `:""}Aster USDT-perpetualuniversum – Top-N</b><br/>
  Gevraagd: {requested} · geschikt: {eligible} · geselecteerd: {selected}<br/>
  Opgehaald: {stamp(data.fetchedAt)} · geldig tot: {stamp(data.expiresAt)}<br/>
  Data: {data.stale===true?"verouderd":"actueel"} · nieuwe instappen: {data.entryBlocked===true?"geblokkeerd":"toegestaan"}
  {data.entryBlockReason?<><br/>{String(data.entryBlockReason)}</>:null}
 </div>
}
