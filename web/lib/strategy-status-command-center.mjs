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
    const hasOrigin=raw.originZone!==null&&raw.originZone!==undefined&&String(raw.originZone).trim()!=="";
    const originRaw=hasOrigin?Number(raw.originZone):NaN;
    const originZone=Number.isInteger(originRaw)?originRaw:null;
    const stable=String(raw.soldierId||raw.cycleId||"").trim();
    result.push({
      id:stable?`${stable}:${atMs}`:`${key}:${atMs}`,
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

function normalizedSide(value) {
  const side=String(value||"").toUpperCase();
  return side==="LONG"||side==="SHORT"?side:"";
}

function amsterdamDayKey(value) {
  const date=new Date(Number(value));
  if(!Number.isFinite(date.getTime()))return "";
  const parts=new Intl.DateTimeFormat("en-GB",{
    timeZone:"Europe/Amsterdam",year:"numeric",month:"2-digit",day:"2-digit",
  }).formatToParts(date);
  const read=(type)=>parts.find((part)=>part.type===type)?.value||"";
  return `${read("year")}-${read("month")}-${read("day")}`;
}

function trueHomecomingIdentity(raw) {
  if(!raw||typeof raw!=="object")return "";
  const reason=String(raw.reason||"").toUpperCase();
  const origin=Number(raw.originZone);
  const current=Number(raw.currentZoneAtClose);
  const closedAtMs=Number(raw.closedAtMs);
  if(
    reason!=="TP_WIN_OUTSIDE_ORIGIN_ZONE"||
    !Number.isInteger(origin)||
    !Number.isInteger(current)||
    origin===current||
    !Number.isFinite(closedAtMs)||
    closedAtMs<=0
  )return "";
  return String(raw.eventId||`${raw.soldierId||raw.side||"soldier"}:${origin}:${current}:${closedAtMs}`);
}

function trueHomecomingEvents(events) {
  const byId=new Map();
  for(const raw of Array.isArray(events)?events:[]){
    const id=trueHomecomingIdentity(raw);
    if(!id)continue;
    byId.set(id,raw);
  }
  return [...byId.values()];
}

export function countWinningHomecomingsToday(events,nowMs=Date.now()) {
  const today=amsterdamDayKey(nowMs);
  let total=0;
  for(const raw of trueHomecomingEvents(events)){
    if(amsterdamDayKey(Number(raw.closedAtMs))===today)total+=1;
  }
  return total;
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
  const zoneFreeLong=Math.min(baseLong,integer(input.zoneFreeLong)??0);
  const zoneFreeShort=Math.min(baseShort,integer(input.zoneFreeShort)??0);
  const zoneOpenLong=Math.min(baseLong,integer(input.zoneOpenLong)??Math.max(0,baseLong-zoneFreeLong));
  const zoneOpenShort=Math.min(baseShort,integer(input.zoneOpenShort)??Math.max(0,baseShort-zoneFreeShort));
  const oldZonesOpenLong=integer(input.oldZonesOpenLong)??0;
  const oldZonesOpenShort=integer(input.oldZonesOpenShort)??0;
  const oldZonesOpenTotal=integer(input.oldZonesOpenTotal)??(oldZonesOpenLong+oldZonesOpenShort);

  const strategyEnabled=input.strategyEnabled===true;
  const zoneSafe=input.zoneSafe===true;
  const rawPriority=normalizedSide(input.entryPriority??input.balancerSide);
  const entryPriority=strategyEnabled&&zoneSafe?rawPriority:"";
  const exposureRaw=String(input.netExposureSide||"").toUpperCase();
  const netExposureSide=exposureRaw==="LONG"||exposureRaw==="SHORT"?exposureRaw:"NEUTRAAL";

  const runtimeBudget=input.entryBudget&&typeof input.entryBudget==="object"?input.entryBudget:null;
  const soldierCost=runtimeBudget&&finite(runtimeBudget.requiredInitialMarginUsd)!==null
    ? finite(runtimeBudget.requiredInitialMarginUsd)
    : estimateSoldierCost(input);
  const runtimeRequiredTotal=runtimeBudget?finite(runtimeBudget.requiredTotalUsd):null;
  const runtimeBudgetStatus=String(runtimeBudget?.status||"").toUpperCase();
  const canonicalBudgetKnown=Boolean(runtimeBudget&&runtimeRequiredTotal!==null&&runtimeRequiredTotal>0);
  const enoughAvailable=canonicalBudgetKnown
    ? runtimeBudgetStatus!=="INSUFFICIENT"&&availableUsd!==null&&availableUsd>=runtimeRequiredTotal
    : false;
  let nextPossibleSide="";
  if(strategyEnabled&&zoneSafe&&enoughAvailable){
    if(entryPriority==="LONG"){
      if(zoneFreeLong>0)nextPossibleSide="LONG";
    }else if(entryPriority==="SHORT"){
      if(zoneFreeShort>0)nextPossibleSide="SHORT";
    }else if(zoneFreeLong>0||zoneFreeShort>0){
      if(zoneFreeLong>0&&zoneFreeShort>0){
        nextPossibleSide=zoneOpenLong<=zoneOpenShort?"LONG":"SHORT";
      }else{
        nextPossibleSide=zoneFreeLong>0?"LONG":"SHORT";
      }
    }
  }

  const homecomingEvents=Array.isArray(input.homecomingEvents)?input.homecomingEvents:[];
  const provenHomecomings=trueHomecomingEvents(homecomingEvents);
  const winningHomeToday=countWinningHomecomingsToday(provenHomecomings,input.nowMs??Date.now());
  const freeZoneSeats=zoneFreeLong+zoneFreeShort;
  const totalZoneSeats=baseLong+baseShort;

  let nextPossibleDetail="alleen als entry geldig is";
  if(!strategyEnabled)nextPossibleDetail="strategie staat uit";
  else if(!zoneSafe)nextPossibleDetail="wacht op bevestigde zone";
  else if(!canonicalBudgetKnown)nextPossibleDetail="wacht op runtime budgetcheck";
  else if(!enoughAvailable){
    const shortfall=finite(runtimeBudget?.shortfallUsd);
    nextPossibleDetail=shortfall!==null&&shortfall>0
      ? `onvoldoende Available · tekort ${formatCommandMoney(shortfall)}`
      : "wacht op voldoende Available";
  }
  else if(entryPriority&&((entryPriority==="LONG"?zoneFreeLong:zoneFreeShort)<=0)){
    nextPossibleDetail=`${entryPriority} prioriteit · geen vrije ${entryPriority}-soldaat`;
  }else if(!nextPossibleSide){
    nextPossibleDetail="formatie is bezet";
  }

  const reconciliation=input.reconciliation&&typeof input.reconciliation==="object"?input.reconciliation:{};
  const categories=reconciliation.categories&&typeof reconciliation.categories==="object"?reconciliation.categories:{};
  const accountLong=integer(reconciliation.exchangeLong)??actualLong;
  const accountShort=integer(reconciliation.exchangeShort)??actualShort;
  const accountTotal=integer(reconciliation.exchangePositions)??(
    accountLong!==null&&accountShort!==null?accountLong+accountShort:null
  );
  const soldiersTotal=integer(reconciliation.soldiersTotal)??totalActiveSoldiers;
  const nonSoldiersTotal=integer(reconciliation.nonSoldiersTotal)??(
    accountTotal!==null&&soldiersTotal!==null?Math.max(0,accountTotal-soldiersTotal):null
  );
  const reconciliationStatus=String(reconciliation.status||"UNKNOWN").toUpperCase();
  const liveDataStatus=String(reconciliation.liveDataStatus||input.liveDataStatus||reconciliationStatus||"UNKNOWN").toUpperCase();
  const snapshotAgeMs=finite(reconciliation.snapshotAgeMs);
  const entryBudget=runtimeBudget?{
    availableUsd:finite(runtimeBudget.availableUsd),
    newSoldierNotionalUsd:finite(runtimeBudget.newSoldierNotionalUsd),
    requiredInitialMarginUsd:finite(runtimeBudget.requiredInitialMarginUsd),
    safetyBufferUsd:finite(runtimeBudget.safetyBufferUsd),
    requiredTotalUsd:finite(runtimeBudget.requiredTotalUsd),
    minimumExchangeOrderMarginUsd:finite(runtimeBudget.minimumExchangeOrderMarginUsd),
    shortfallUsd:finite(runtimeBudget.shortfallUsd),
    status:runtimeBudgetStatus||"UNKNOWN",
    source:String(runtimeBudget.source||""),
  }:null;

  return {
    reference:"file_000000009e0081f4b88f4b415de68c71",
    strategyEnabled,
    zoneSafe,
    activeZone:zoneLabel(input.activeZone),
    desiredLong:baseLong,
    desiredShort:baseShort,
    formationHardCap:true,
    zoneOpenLong,
    zoneOpenShort,
    zoneFreeLong,
    zoneFreeShort,
    freeZoneSeats,
    totalZoneSeats,
    oldZonesOpenTotal,
    oldZonesOpenLong,
    oldZonesOpenShort,
    actualLong,
    actualShort,
    totalActiveSoldiers,
    netExposureSide,
    entryPriority:entryPriority||"GEEN",
    nextPossibleSide,
    nextPossibleInflow:nextPossibleSide?`1 ${nextPossibleSide}`:"GEEN",
    nextPossibleDetail,
    winningHomeToday,
    winningHomeTotal:provenHomecomings.length,
    availableUsd,
    availableDisplay:String(input.availableText||formatCommandMoney(availableUsd)),
    estimatedSoldierCost:soldierCost,
    entryBudget,
    reconciliationStatus,
    liveDataStatus,
    snapshotId:String(reconciliation.snapshotId||""),
    snapshotAgeMs,
    accountLong,
    accountShort,
    accountTotal,
    soldiersTotal,
    nonSoldiersTotal,
    unknownPositions:integer(reconciliation.unknownPositions)??integer(categories.unknown)??0,
    legacyAster:integer(categories.legacyAster)??0,
    previousStrategy:integer(categories.previousStrategy)??0,
    sniperPositions:integer(categories.sniper)??0,
    soldierCurrentZone:integer(categories.soldiersCurrentZone)??zoneOpenLong+zoneOpenShort,
    soldierOldZones:integer(categories.soldiersOldZones)??oldZonesOpenTotal,
    longExposureUsd:finite(reconciliation.longExposureUsd),
    shortExposureUsd:finite(reconciliation.shortExposureUsd),
    netExposureUsd:finite(reconciliation.netExposureUsd),
    hedgeCoveragePercent:finite(reconciliation.hedgeCoveragePercent),
    exchangeAvailableUsd:finite(reconciliation.margin?.availableUsd),
    appAvailableUsd:availableUsd,
    classifiedPositions:integer(reconciliation.classifiedPositions),
    unclassifiedPositions:integer(reconciliation.unclassifiedPositions),
    actionExecutable:Boolean(nextPossibleSide),
    actionMode:nextPossibleSide?nextPossibleSide.toLowerCase():strategyEnabled&&zoneSafe?"waiting":"blocked",
    footerTitle:"Alleen oude-zone soldaten tellen als thuiskomst",
    footerDetail:"Winst in de eigen actieve zone maakt dezelfde soldaat opnieuw beschikbaar",
    soldierActivity:summarizeSoldierActivity(input.soldierActivity,input.nowMs??Date.now()),
  };
}
