function stamp(value:unknown){
 if(!value)return "—";
 const parsed=new Date(String(value));
 return Number.isNaN(parsed.getTime())?String(value):parsed.toLocaleString("nl-NL");
}

export function AsterUniverseStatus({value,label=""}:{value:unknown;label?:string}){
 const data=(value&&typeof value==="object"?value:{}) as Record<string,unknown>;
 const requested=Number(data.requestedTopN||0),eligible=Number(data.eligibleMarketCount||0),selected=Number(data.selectedMarketCount||0);
 const discovered=Number(data.discoveredMarketCount||0);
 const unavailable=Array.isArray(data.unavailableFilters)?data.unavailableFilters.map(String):[];
 if(!requested&&!eligible&&!selected)return <div className="strategy-message warn"><b>{label?`${label} · `:""}Aster USDT-perpetualuniversum</b><br/>Nog niet server-side ververst. Alleen nieuwe instappen blijven geblokkeerd.</div>;
 return <div className={`strategy-message ${data.entryBlocked===true?"warn":"ok"}`}>
  <b>{label?`${label} · `:""}Top‑N op Aster 24-uurs USDT-handelsvolume, na liquiditeits- en veiligheidsfilters.</b><br/>
  Gevonden: {discovered} · gevraagd: {requested} · geschikt: {eligible} · geselecteerd: {selected}<br/>
  Opgehaald: {stamp(data.fetchedAt)} · geldig tot: {stamp(data.expiresAt)}<br/>
  Data: {data.stale===true?"verouderd":"actueel"} · nieuwe instappen: {data.entryBlocked===true?"geblokkeerd":"toegestaan"}
  {data.entryBlockReason?<><br/>{String(data.entryBlockReason)}</>:null}
  {unavailable.length?<><br/>Niet aantoonbaar beschikbaar: {unavailable.join(", ")}</>:null}
 </div>
}
