export const COMMAND_CENTER_HEALTH_THRESHOLDS = Object.freeze({
  criticalDcaRounds: 1,
  cautionDcaRounds: 3,
  healthyDcaRounds: 7,
  unlimitedReferenceRounds: 12,
});

export const SOLDIER_ACTIVITY_WINDOWS = Object.freeze([
  { key:"15m", label:"15m", ms:15*60*1000 },
  { key:"1u", label:"1u", ms:60*60*1000 },
  { key:"4u", label:"4u", ms:4*60*60*1000 },
  { key:"24u", label:"24u", ms:24*60*60*1000 },
]);

const SOLDIER_ROLES = new Set(["ZONE_BASE","EXPOSURE_BALANCER"]);

export function soldierOpenEventsFromManagedPositions(rawPositions) {
  const source=rawPositions&&typeof rawPositions==="object"?rawPositions:{};
  const result=[];
  for(const [key,raw] of Object.entries(source)){
    if(!raw||typeof raw!=="object")continue;
    const role=String(raw.soldierRole||"").toUpperCase().trim();
    if(!SOLDIER_ROLES.has(role))continue;
    if(raw.adoptedExisting===true||raw.recoveredFromSelectedOpenPosition===true)continue;
    const side=String(key).toUpperCase().endsWith("|SHORT")?"SHORT":String(key).toUpperCase().endsWith("|LONG")?"LONG":"";
    const atMs=Math.floor(Number(raw.cycleStartedAtMs));
    if(!side||!Number.isFinite(atMs)||atMs<=0)continue;
    const originRaw=Number(raw.originZone);
    const originZone=Number.isInteger(originRaw)?originRaw:null;
    const stable=String(raw.soldierId||raw.cycleId||"").trim();
    result.push({
      id:stable||`${key}:${atMs}`,
      atMs,
      side,
      count:1,
      originZone,
      role,
      source:"confirmed-zone-soldier-open",
    });
  }
  return result.sort((a,b)=>b.atMs-a.atMs||String(a.id).localeCompare(String(b.id)));
}

export function mergeSoldierActivityHistory(existing,current,nowMs=Date.now()) {
  const cutoff=Math.max(0,Number(nowMs)-25*60*60*1000);
  const rows=[...(Array.isArray(existing)?existing:[]),...(Array.isArray(current)?current:[])];
  const byId=new Map();
  for(const raw of rows){
    if(!raw||typeof raw!=="object")continue;
    const atMs=Math.floor(Number(raw.atMs));
    const side=String(raw.side||"").toUpperCase();
    const count=Math.max(1,Math.floor(Number(raw.count)||1));
    if(!Number.isFinite(atMs)||atMs<cutoff||!["LONG","SHORT"].includes(side))continue;
    const id=String(raw.id||`${side}:${atMs}:${raw.originZone??""}`);
    byId.set(id,{...raw,id,atMs,side,count});
  }
  return [...byId.values()].sort((a,b)=>b.atMs-a.atMs||String(a.id).localeCompare(String(b.id)));
}

export function summarizeSoldierActivity(events,nowMs=Date.now()) {
  const now=Number(nowMs);
  const clean=(Array.isArray(events)?events:[])
    .filter((row)=>row&&["LONG","SHORT"].includes(String(row.side||"").toUpperCase())&&Number.isFinite(Number(row.atMs)))
    .map((row)=>({...row,side:String(row.side).toUpperCase(),atMs:Number(row.atMs),count:Math.max(1,Math.floor(Number(row.count)||1))}))
    .sort((a,b)=>b.atMs-a.atMs||String(a.id||"").localeCompare(String(b.id||"")));
  const windows={};
  for(const spec of SOLDIER_ACTIVITY_WINDOWS){
    let long=0,short=0;
    for(const row of clean){
      if(row.atMs>now||row.atMs<now-spec.ms)continue;
      if(row.side==="LONG")long+=row.count;
      else short+=row.count;
    }
    windows[spec.key]={key:spec.key,label:spec.label,long,short,total:long+short};
  }
  const recent=clean.filter((row)=>row.atMs<=now&&row.atMs>=now-24*60*60*1000).slice(0,3);
  return {windows,recent,total24h:windows["24u"].total};
}

function finite(value) {
  const number=Number(value);
  return Number.isFinite(number)?number:null;
}

function integer(value) {
  const number=finite(value);
  return number===null?null:Math.max(0,Math.round(number));
}

export function parsePortfolioMoney(value) {
  if(typeof value==="number")return Number.isFinite(value)?value:null;
  const raw=String(value??"").trim();
  if(!raw||raw==="—")return null;
  const cleaned=raw.replace(/[^-0-9,.+]/g,"");
  if(!cleaned)return null;
  const comma=cleaned.lastIndexOf(",");
  const dot=cleaned.lastIndexOf(".");
  let normalized=cleaned;
  if(comma>=0&&dot>=0){
    normalized=comma>dot
      ? cleaned.replaceAll(".","").replace(",",".")
      : cleaned.replaceAll(",","");
  }else if(comma>=0){
    normalized=cleaned.replaceAll(".","").replace(",",".");
  }else if((cleaned.match(/\./g)||[]).length>1){
    const last=cleaned.lastIndexOf(".");
    normalized=cleaned.slice(0,last).replaceAll(".","")+cleaned.slice(last);
  }
  const result=Number(normalized);
  return Number.isFinite(result)?result:null;
}

export function formatCommandMoney(value) {
  const number=finite(value);
  if(number===null)return "—";
  return `US$ ${new Intl.NumberFormat("nl-NL",{minimumFractionDigits:2,maximumFractionDigits:2}).format(number)}`;
}

function zoneLabel(value) {
  const number=finite(value);
  if(number===null)return "—";
  const index=Math.round(number);
  return index===0?"Z0":index>0?`Z+${index}`:`Z${index}`;
}

function distancePercent(target,current) {
  const targetValue=finite(target),currentValue=finite(current);
  if(targetValue===null||currentValue===null||currentValue<=0)return null;
  return ((targetValue-currentValue)/currentValue)*100;
}

function formatPercent(value) {
  const number=finite(value);
  if(number===null)return "—";
  const prefix=number>0?"+":number<0?"−":"";
  return `${prefix}${new Intl.NumberFormat("nl-NL",{minimumFractionDigits:2,maximumFractionDigits:2}).format(Math.abs(number))}%`;
}

function estimateSoldierCost(input) {
  const activeEntry=finite(input.activeZoneEntryUsd);
  if(activeEntry===null||activeEntry<=0)return null;
  const mode=String(input.entrySizingMode||"").toLowerCase();
  const leverage=Math.max(1,finite(input.minimumLeverage)??1);
  const marginCost=mode==="notional"?activeEntry/leverage:activeEntry;
  const fee=finite(input.entryFeeBufferUsd)??0;
  const minimum=finite(input.minimumOrderMarginUsd)??0;
  return Math.max(minimum,marginCost+Math.max(0,fee));
}

function estimateDcaCost(input) {
  const configured=finite(input.dcaMarginUsd);
  if(configured===null||configured<=0)return null;
  const fee=finite(input.dcaFeeBufferUsd)??0;
  const minimum=finite(input.minimumOrderMarginUsd)??0;
  return Math.max(minimum,configured+Math.max(0,fee));
}

function affordable(available,cost) {
  if(available===null||cost===null||available<0||cost<=0)return null;
  return Math.max(0,Math.floor(available/cost));
}

function healthState({availableUsd,estimatedAffordableSoldiers,estimatedDcaRounds,pendingCount}) {
  if(availableUsd!==null&&availableUsd<=0)return "KRAP";
  if(estimatedAffordableSoldiers!==null&&pendingCount>0&&estimatedAffordableSoldiers<pendingCount)return "KRAP";
  if(estimatedDcaRounds!==null&&estimatedDcaRounds<=COMMAND_CENTER_HEALTH_THRESHOLDS.criticalDcaRounds)return "KRAP";
  if(estimatedDcaRounds!==null&&estimatedDcaRounds<=COMMAND_CENTER_HEALTH_THRESHOLDS.cautionDcaRounds)return "OPLETTEN";
  if(estimatedDcaRounds!==null&&estimatedDcaRounds<=COMMAND_CENTER_HEALTH_THRESHOLDS.healthyDcaRounds)return "GEZOND";
  return "RUIM";
}

export function buildStrategyStatusCommandCenter(input={}) {
  const availableUsd=parsePortfolioMoney(input.availableText??input.availableUsd);
  const actualLong=integer(input.actualLong);
  const actualShort=integer(input.actualShort);
  const totalActiveSoldiers=actualLong!==null&&actualShort!==null
    ? actualLong+actualShort
    : integer(input.totalActive);

  const baseLong=integer(input.baseLong)??0;
  const baseShort=integer(input.baseShort)??0;
  const zoneFreeLong=integer(input.zoneFreeLong)??0;
  const zoneFreeShort=integer(input.zoneFreeShort)??0;
  const balancerFree=integer(input.balancerFree)??0;
  const balancerDesired=integer(input.balancerDesired)??0;
  const balancerOpen=integer(input.balancerOpen)??0;
  const pendingCount=Math.max(0,integer(input.pendingCount)??Math.max(0,balancerDesired-balancerOpen));
  const pendingSide=["LONG","SHORT"].includes(String(input.pendingSide||"").toUpperCase())
    ? String(input.pendingSide).toUpperCase()
    : "";

  const soldierCost=estimateSoldierCost(input);
  const dcaCost=estimateDcaCost(input);
  const estimatedAffordableSoldiers=affordable(availableUsd,soldierCost);
  const estimatedDcaRounds=affordable(availableUsd,dcaCost);

  const freeZoneSeats=zoneFreeLong+zoneFreeShort+balancerFree;
  const totalZoneSeats=Math.max(
    freeZoneSeats,
    baseLong+baseShort+balancerDesired,
  );
  const relevantFreeSeats=pendingSide==="LONG"
    ? zoneFreeLong+(String(input.balancerSide||"").toUpperCase()==="LONG"?balancerFree:0)
    : pendingSide==="SHORT"
      ? zoneFreeShort+(String(input.balancerSide||"").toUpperCase()==="SHORT"?balancerFree:0)
      : freeZoneSeats;

  const strategyEnabled=input.strategyEnabled===true;
  const zoneSafe=input.zoneSafe===true;
  const hasEnoughForOne=soldierCost===null||availableUsd===null?availableUsd===null||availableUsd>0:availableUsd>=soldierCost;
  const hasEnoughForPending=pendingCount<=0||estimatedAffordableSoldiers===null||estimatedAffordableSoldiers>=pendingCount;
  const hasSeats=pendingCount<=0||relevantFreeSeats>0;
  const actionExecutable=Boolean(strategyEnabled&&zoneSafe&&hasEnoughForOne&&hasEnoughForPending&&hasSeats);

  let actionTitle="Geen actie nodig";
  let actionDetail="De strategie volgt de actieve zone.";
  let actionMode="idle";
  if(!strategyEnabled){
    actionTitle="Geblokkeerd — strategy uit";
    actionDetail="De Zone-Soldatenstrategie plaatst geen nieuwe orders.";
    actionMode="blocked";
  }else if(!zoneSafe){
    actionTitle="Wachten op zone";
    actionDetail="De 15m-zone is nog niet veilig bevestigd voor nieuwe entries.";
    actionMode="waiting";
  }else if(pendingCount>0&&pendingSide){
    if(!hasEnoughForOne||!hasEnoughForPending){
      actionTitle="Geblokkeerd — onvoldoende available";
      actionDetail=estimatedAffordableSoldiers===null
        ? `+${pendingCount} ${pendingSide} gewenst; betaalbaarheid kan niet betrouwbaar worden berekend.`
        : `${estimatedAffordableSoldiers} van ${pendingCount} gewenste ${pendingSide}-soldaten zijn met huidig Available betaalbaar.`;
      actionMode="blocked";
    }else if(!hasSeats){
      actionTitle="Geblokkeerd — geen vrije stoelen";
      actionDetail=`+${pendingCount} ${pendingSide} gewenst, maar er is nu geen vrije zone-capaciteit.`;
      actionMode="blocked";
    }else{
      actionTitle=`+${pendingCount} ${pendingSide} automatisch`;
      actionDetail=`${zoneLabel(input.activeZone)} bevestigd · de bot verwerkt dit automatisch via het bestaande entrypad.`;
      actionMode=pendingSide==="LONG"?"long":"short";
    }
  }else if(freeZoneSeats>0){
    actionTitle="Wachten op entry";
    actionDetail=`${freeZoneSeats} zone-soldaat${freeZoneSeats===1?"":"en"} staan nog vrij en worden automatisch gebruikt bij geldige entries.`;
    actionMode="waiting";
  }else{
    actionTitle="Formatie compleet";
    actionDetail="De actieve zone heeft momenteel geen open formatie-tekort.";
    actionMode="complete";
  }

  const longPercent=totalActiveSoldiers&&actualLong!==null?(actualLong/totalActiveSoldiers)*100:null;
  const shortPercent=totalActiveSoldiers&&actualShort!==null?(actualShort/totalActiveSoldiers)*100:null;

  const maxDca=integer(input.maxDca);
  const unlimitedDca=input.unlimitedDca===true;
  const runwayTarget=unlimitedDca
    ? COMMAND_CENTER_HEALTH_THRESHOLDS.unlimitedReferenceRounds
    : Math.max(1,maxDca??COMMAND_CENTER_HEALTH_THRESHOLDS.unlimitedReferenceRounds);
  const dcaCoveragePercent=estimatedDcaRounds===null
    ? null
    : Math.max(0,Math.min(100,(estimatedDcaRounds/runwayTarget)*100));

  const health=healthState({availableUsd,estimatedAffordableSoldiers,estimatedDcaRounds,pendingCount});
  const currentLower=finite(input.currentZoneLower);
  const currentUpper=finite(input.currentZoneUpper);
  const currentZoneRange=currentLower!==null&&currentUpper!==null
    ? `${new Intl.NumberFormat("nl-NL",{minimumFractionDigits:2,maximumFractionDigits:2}).format(currentLower)}–${new Intl.NumberFormat("nl-NL",{minimumFractionDigits:2,maximumFractionDigits:2}).format(currentUpper)}`
    : "—";

  let footerTitle="Bot koopt zelf bij zolang Available en vrije zone-soldaten beschikbaar zijn";
  let footerDetail="De strategie gebruikt uitsluitend het bestaande automatische zone-entrypad. Geen handmatige actie nodig.";
  if(!strategyEnabled){
    footerTitle="Strategie staat uit — geen nieuwe zone-orders";
    footerDetail="Bestaande posities blijven door hun bestaande beheerlogica afgehandeld.";
  }else if(!zoneSafe){
    footerTitle="Automatische zone-entry wacht";
    footerDetail="Nieuwe entries blijven geblokkeerd totdat de bevestigde 15m-zone weer veilig is.";
  }else if(actionMode==="blocked"){
    footerTitle=actionTitle;
    footerDetail=actionDetail;
  }else if(freeZoneSeats<=0&&pendingCount<=0){
    footerTitle="Actieve zone is gevuld";
    footerDetail="De bot wacht op een geldige nieuwe zone of vrijgekomen zone-capaciteit.";
  }

  return {
    reference:"file_00000000d9b0820e8eacdecb418c95aa",
    strategyEnabled,
    autoRefillEnabled:strategyEnabled,
    zoneSafe,
    activeZone:zoneLabel(input.activeZone),
    nextZone:zoneLabel(input.nextZone),
    previousZone:zoneLabel(input.previousZone),
    currentZoneRange,
    nextZonePrice:finite(input.nextZonePrice),
    previousZonePrice:finite(input.previousZonePrice),
    nextZoneDistancePercent:distancePercent(input.nextZonePrice,input.currentEquity),
    previousZoneDistancePercent:distancePercent(input.previousZonePrice,input.currentEquity),
    desiredLong:baseLong,
    desiredShort:baseShort,
    actualLong,
    actualShort,
    totalActiveSoldiers,
    longPercent,
    shortPercent,
    pendingSide,
    pendingCount,
    actionTitle,
    actionDetail,
    actionMode,
    actionExecutable,
    availableUsd,
    availableDisplay:String(input.availableText||formatCommandMoney(availableUsd)),
    estimatedSoldierCost:soldierCost,
    estimatedAffordableSoldiers,
    estimatedDcaCost:dcaCost,
    estimatedDcaRounds,
    dcaCoveragePercent,
    freeZoneSeats,
    totalZoneSeats,
    zoneFreeLong,
    zoneFreeShort,
    balancerFree,
    healthState:health,
    maxDca,
    unlimitedDca,
    footerTitle,
    footerDetail,
    nextZoneDisplay:finite(input.nextZonePrice)===null?"—":`${formatCommandMoney(input.nextZonePrice)} (${formatPercent(distancePercent(input.nextZonePrice,input.currentEquity))})`,
    previousZoneDisplay:finite(input.previousZonePrice)===null?"—":`${formatCommandMoney(input.previousZonePrice)} (${formatPercent(distancePercent(input.previousZonePrice,input.currentEquity))})`,
    estimateCaveat:"Schatting op basis van actuele sizing/configuratiemarge; niet-beschikbare fee- of marktminimumdata wordt niet verzonnen.",
    soldierActivity:summarizeSoldierActivity(input.soldierActivity,input.nowMs??Date.now()),
  };
}
