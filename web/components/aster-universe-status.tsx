export function AsterUniverseStatus({value}:{value:unknown}){
 const data=(value&&typeof value==="object"?value:{}) as Record<string,unknown>;
 const requested=Number(data.requestedTopN||0),eligible=Number(data.eligibleMarketCount||0),selected=Number(data.selectedMarketCount||0);
 if(!requested)return null;
 return <div className={`strategy-message ${data.entryBlocked===true?"warn":"ok"}`}><b>Aster USDT-handelsuniversum – Top-N op volume en liquiditeit</b><br/>Ingesteld: {requested} · beschikbaar: {eligible} · geselecteerd: {selected}{data.entryBlockReason?<><br/>{String(data.entryBlockReason)}</>:null}</div>
}
