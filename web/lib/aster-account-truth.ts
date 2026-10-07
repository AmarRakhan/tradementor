export type AsterAccountTruth = {
  schemaVersion: number;
  contract: string;
  source: string;
  capturedAtMs: number | null;
  stale: boolean;
  configured: boolean;
  readOnly: boolean;
  ordersSent: number;
  account: {
    equity: number | null;
    walletBalance: number | null;
    availableBalance: number | null;
    activeTradeCapital: number | null;
    unrealizedPnl: number | null;
    maintenanceMargin: number | null;
    maintenanceMarginPct: number | null;
    marginRatio: number | null;
    marginBalance: number | null;
    liquidationRiskPct: number | null;
    liquidationRiskSource: string;
    longNotional: number | null;
    shortNotional: number | null;
    netExposure: number | null;
    grossExposure: number | null;
  };
  positions: {
    count: number;
    longCount: number;
    shortCount: number;
    rows: Record<string, unknown>[];
  };
  performance: {
    dayHigh: number | null;
    dayLow: number | null;
    realizedPnlToday: number | null;
    tradesClosedToday: number | null;
    closedTodayReliable: boolean;
    todayGrowthPercentage: number | null;
    averageDailyGrowthPercentage: number | null;
    growthReliable: boolean;
  };
  strategy: {
    settings: Record<string, unknown>;
    runtimeTruth: Record<string, unknown>;
    summary: {
      enabled: boolean;
      monitor: boolean;
      activeLong: number;
      activeShort: number;
      longCapacity: number | null;
      shortCapacity: number | null;
      dcaCount: number;
      phase: string;
    };
  };
  provenance: Record<string, unknown>;
};

const record=(value:unknown):Record<string,unknown>=>value&&typeof value==="object"&&!Array.isArray(value)?value as Record<string,unknown>:{};
const nullableNumber=(value:unknown):number|null=>{
  if(value===null||value===undefined||value==="")return null;
  const number=Number(value);
  return Number.isFinite(number)?number:null;
};
const nonNegativeInt=(value:unknown, fallback=0):number=>{
  const number=Number(value);
  return Number.isFinite(number)?Math.max(0,Math.round(number)):fallback;
};

export function normalizeAsterAccountTruth(payload: unknown): AsterAccountTruth {
  const root=record(payload);
  const raw=record(root.accountTruth);
  if(raw.contract!=="ASTER_ACCOUNT_TRUTH_V1"||Number(raw.schemaVersion)!==1||raw.readOnly!==true||Number(raw.ordersSent)!==0){
    throw new Error("Canonical Aster account truth ontbreekt of heeft een onbekend schema.");
  }
  const account=record(raw.account);
  const positions=record(raw.positions);
  const performance=record(raw.performance);
  const strategy=record(raw.strategy);
  const summary=record(strategy.summary);
  return {
    schemaVersion:1,
    contract:"ASTER_ACCOUNT_TRUTH_V1",
    source:String(raw.source||""),
    capturedAtMs:nullableNumber(raw.capturedAtMs),
    stale:raw.stale===true,
    configured:raw.configured===true,
    readOnly:true,
    ordersSent:0,
    account:{
      equity:nullableNumber(account.equity),
      walletBalance:nullableNumber(account.walletBalance),
      availableBalance:nullableNumber(account.availableBalance),
      activeTradeCapital:nullableNumber(account.activeTradeCapital),
      unrealizedPnl:nullableNumber(account.unrealizedPnl),
      maintenanceMargin:nullableNumber(account.maintenanceMargin),
      maintenanceMarginPct:nullableNumber(account.maintenanceMarginPct),
      marginRatio:nullableNumber(account.marginRatio),
      marginBalance:nullableNumber(account.marginBalance),
      liquidationRiskPct:nullableNumber(account.liquidationRiskPct),
      liquidationRiskSource:String(account.liquidationRiskSource||""),
      longNotional:nullableNumber(account.longNotional),
      shortNotional:nullableNumber(account.shortNotional),
      netExposure:nullableNumber(account.netExposure),
      grossExposure:nullableNumber(account.grossExposure),
    },
    positions:{
      count:nonNegativeInt(positions.count),
      longCount:nonNegativeInt(positions.longCount),
      shortCount:nonNegativeInt(positions.shortCount),
      rows:Array.isArray(positions.rows)?(positions.rows.filter((row)=>row&&typeof row==="object") as Record<string,unknown>[]):[],
    },
    performance:{
      dayHigh:nullableNumber(performance.dayHigh),
      dayLow:nullableNumber(performance.dayLow),
      realizedPnlToday:performance.closedTodayReliable===true?nullableNumber(performance.realizedPnlToday):null,
      tradesClosedToday:performance.closedTodayReliable===true?nullableNumber(performance.tradesClosedToday):null,
      closedTodayReliable:performance.closedTodayReliable===true,
      todayGrowthPercentage:performance.growthReliable===true?nullableNumber(performance.todayGrowthPercentage):null,
      averageDailyGrowthPercentage:performance.growthReliable===true?nullableNumber(performance.averageDailyGrowthPercentage):null,
      growthReliable:performance.growthReliable===true,
    },
    strategy:{
      settings:record(strategy.settings),
      runtimeTruth:record(strategy.runtimeTruth),
      summary:{
        enabled:summary.enabled===true,
        monitor:summary.monitor===true,
        activeLong:nonNegativeInt(summary.activeLong),
        activeShort:nonNegativeInt(summary.activeShort),
        longCapacity:nullableNumber(summary.longCapacity),
        shortCapacity:nullableNumber(summary.shortCapacity),
        dcaCount:nonNegativeInt(summary.dcaCount),
        phase:String(summary.phase||""),
      },
    },
    provenance:record(raw.provenance),
  };
}
