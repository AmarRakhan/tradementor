export type BotEntryStatus = "ALLOWED" | "WAITING" | "BLOCKED" | "UNKNOWN";
export type BotRuntimeStatus = "LIVE" | "PAPER" | "STOPPED" | "BLOCKED" | "RECOVERING" | "UNKNOWN";
export type BotCheck = { code: string; status: "PASS" | "WAIT" | "BLOCK" | "UNKNOWN"; text: string };
export type StrategyDashboardStatus = {
  status: BotRuntimeStatus; mode: "LIVE" | "PAPER"; enabled: boolean; monitor: boolean;
  phase: string; ownedPositions: number; lastTickAt: unknown; lastAction: string;
  lastActionAt: unknown; lastReason: string; ownershipStatus: string;
  schedulerStatus: { status: string; lastTickAt: unknown; ageSeconds: number | null; warning: string };
  liveGates: Record<string, boolean>; maximumPositions?: number; remainingAccountCapacity?: number;
};
export type AsterBotStatus = {
  evaluatedAt: unknown; exchangeDataAt: unknown; dataFresh: boolean;
  account: { activePositions: number; longPositions: number; shortPositions: number; openOrders: number; maintenanceMarginPercent: number };
  strategy2: StrategyDashboardStatus; strategy3: StrategyDashboardStatus & { maximumPositions: number; remainingAccountCapacity: number };
  newEntry: { status: BotEntryStatus; reasonCode: string; reasonText: string; strategyId: string; checkedAt: unknown; checks: BotCheck[]; activeBlocks: BotCheck[] };
  nextExpectedCheckAt: unknown;
  evidence: { accountCountsConsistent: boolean; unknownOwnershipCount: number; ownershipConflictCount: number; browserDerived: false };
};

const record = (value: unknown): Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
const finite = (value: unknown): number | null => { const number = Number(value); return Number.isFinite(number) ? number : null; };
const statuses = new Set<BotRuntimeStatus>(["LIVE", "PAPER", "STOPPED", "BLOCKED", "RECOVERING", "UNKNOWN"]);
const entryStatuses = new Set<BotEntryStatus>(["ALLOWED", "WAITING", "BLOCKED", "UNKNOWN"]);
const checkStatuses = new Set(["PASS", "WAIT", "BLOCK", "UNKNOWN"]);

function parseChecks(value: unknown): BotCheck[] | null {
  if (!Array.isArray(value)) return null;
  const result: BotCheck[] = [];
  for (const item of value) {
    const row = record(item); const status = String(row.status || "");
    if (!row.code || !row.text || !checkStatuses.has(status)) return null;
    result.push({ code: String(row.code), status: status as BotCheck["status"], text: String(row.text) });
  }
  return result;
}

function parseStrategy(value: unknown): StrategyDashboardStatus | null {
  const row = record(value); const scheduler = record(row.schedulerStatus); const gates = record(row.liveGates);
  const status = String(row.status || "") as BotRuntimeStatus; const mode = String(row.mode || "");
  const ownedPositions = finite(row.ownedPositions); const age = scheduler.ageSeconds === null ? null : finite(scheduler.ageSeconds);
  if (!statuses.has(status) || !["LIVE", "PAPER"].includes(mode) || ownedPositions === null || !row.schedulerStatus || !row.liveGates) return null;
  return { status, mode: mode as "LIVE" | "PAPER", enabled: row.enabled === true, monitor: row.monitor === true,
    phase: String(row.phase || "UNKNOWN"), ownedPositions, lastTickAt: row.lastTickAt,
    lastAction: String(row.lastAction || "NIET_BEWEZEN"), lastActionAt: row.lastActionAt,
    lastReason: String(row.lastReason || "Geen bewezen reden beschikbaar"), ownershipStatus: String(row.ownershipStatus || "UNKNOWN"),
    schedulerStatus: { status: String(scheduler.status || "STALE"), lastTickAt: scheduler.lastTickAt,
      ageSeconds: age, warning: String(scheduler.warning || "") },
    liveGates: Object.fromEntries(Object.entries(gates).map(([key, gate]) => [key, gate === true])) };
}

export function parseAsterBotStatus(snapshot: unknown): AsterBotStatus | null {
  const source = record(snapshot); const row = record(source.botStatusDashboard); const account = record(row.account);
  const entry = record(row.newEntry); const evidence = record(row.evidence);
  const strategy2 = parseStrategy(row.strategy2); const strategy3 = parseStrategy(row.strategy3);
  const active = finite(account.activePositions); const long = finite(account.longPositions); const short = finite(account.shortPositions);
  const orders = finite(account.openOrders); const maintenance = finite(account.maintenanceMarginPercent);
  const maximum = finite(record(row.strategy3).maximumPositions); const remaining = finite(record(row.strategy3).remainingAccountCapacity);
  const status = String(entry.status || "") as BotEntryStatus; const checks = parseChecks(entry.checks); const activeBlocks = parseChecks(entry.activeBlocks);
  if (!strategy2 || !strategy3 || active === null || long === null || short === null || orders === null || maintenance === null
    || maximum === null || remaining === null || !entryStatuses.has(status) || !checks || !activeBlocks
    || evidence.browserDerived !== false) return null;
  return { evaluatedAt: row.evaluatedAt, exchangeDataAt: row.exchangeDataAt, dataFresh: row.dataFresh === true,
    account: { activePositions: active, longPositions: long, shortPositions: short, openOrders: orders, maintenanceMarginPercent: maintenance },
    strategy2, strategy3: { ...strategy3, maximumPositions: maximum, remainingAccountCapacity: remaining },
    newEntry: { status, reasonCode: String(entry.reasonCode || "UNKNOWN"), reasonText: String(entry.reasonText || "Status niet betrouwbaar"),
      strategyId: String(entry.strategyId || "aster-strategy-3"), checkedAt: entry.checkedAt, checks, activeBlocks },
    nextExpectedCheckAt: row.nextExpectedCheckAt,
    evidence: { accountCountsConsistent: evidence.accountCountsConsistent === true,
      unknownOwnershipCount: finite(evidence.unknownOwnershipCount) || 0,
      ownershipConflictCount: finite(evidence.ownershipConflictCount) || 0, browserDerived: false } };
}
