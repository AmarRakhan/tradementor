export type PortfolioTimeframe = "1m" | "5m" | "15m" | "1u" | "4u" | "24u";

export type PortfolioEquityCandle = {
  timeMs: number;
  open: number;
  high: number;
  low: number;
  close: number;
  sampleCount?: number;
};

export type PortfolioBollingerPoint = {
  timeMs: number;
  middle: number;
  upper: number;
  lower: number;
};

export type PortfolioZone = {
  index: number;
  label: string;
  lower: number;
  upper: number;
  confirmed: boolean;
  active: boolean;
};

export type PortfolioBollingerEvent = {
  kind: "bb_upper" | "bb_lower" | "bb_reentry";
  timeMs: number;
  equity: number;
  bandValue?: number;
  from?: string;
};

export type PortfolioEquityChartResponse = {
  reliable: boolean;
  readOnly: boolean;
  ordersSent: number;
  currency: string;
  equitySource: string;
  equityDefinition: string;
  rawEquity: number;
  cashflowAdjusted: boolean;
  cashflowComplete: boolean;
  timeframe: string;
  sampleCadenceSeconds: number;
  historyStartMs: number | null;
  historyCoverageNote: string;
  anchorEquity: number | null;
  candles: PortfolioEquityCandle[];
  bollinger: PortfolioBollingerPoint[];
  bollingerEvents: PortfolioBollingerEvent[];
  zones: {
    levels?: Array<Record<string, unknown>>;
    zones: PortfolioZone[];
    activeZone?: PortfolioZone | null;
  };
  shadow?: Record<string, unknown>;
};

export type RecentTradeActivity = {
  entries?: Array<Record<string, unknown>>;
  exits?: Array<Record<string, unknown>>;
};

export type PortfolioChartMarker = {
  time: number;
  position: "aboveBar" | "belowBar" | "inBar";
  color: string;
  shape: "circle" | "square" | "arrowUp" | "arrowDown";
  text: string;
  size: number;
  kind: "entry" | "profit" | "profit-dot" | "bb";
};

export const PORTFOLIO_TIMEFRAMES: PortfolioTimeframe[] = ["1m", "5m", "15m", "1u", "4u", "24u"];

export function apiPortfolioTimeframe(value: PortfolioTimeframe) {
  if (value === "1u") return "1h";
  if (value === "4u") return "4h";
  if (value === "24u") return "24h";
  return value;
}

export function portfolioTimeframeMs(value: PortfolioTimeframe) {
  const api = apiPortfolioTimeframe(value);
  if (api === "1m") return 60_000;
  if (api === "5m") return 300_000;
  if (api === "15m") return 900_000;
  if (api === "1h") return 3_600_000;
  if (api === "4h") return 14_400_000;
  return 86_400_000;
}

function finite(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function sideLetter(value: unknown) {
  const side = String(value || "").toUpperCase();
  return side === "LONG" ? "L" : side === "SHORT" ? "S" : "";
}

function bucketForEvent(timestampMs: number, candles: PortfolioEquityCandle[], bucketMs: number) {
  if (!candles.length || !Number.isFinite(timestampMs) || timestampMs <= 0) return null;
  const bucket = Math.floor(timestampMs / bucketMs) * bucketMs;
  const exact = candles.find((row) => row.timeMs === bucket);
  if (exact) return exact.timeMs;
  let nearest: PortfolioEquityCandle | null = null;
  let distance = Number.POSITIVE_INFINITY;
  for (const row of candles) {
    const next = Math.abs(row.timeMs - bucket);
    if (next < distance && next <= bucketMs) {
      distance = next;
      nearest = row;
    }
  }
  return nearest?.timeMs ?? null;
}

export function formatPortfolioUsd(value: number) {
  return new Intl.NumberFormat("nl-NL", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value).replace("US$", "$");
}

type TimedActivity = {
  timeMs: number;
  side: "L" | "S";
  realizedPnlUsd: number;
};

function normalizedActivity(
  rows: Array<Record<string, unknown>> | undefined,
  candles: PortfolioEquityCandle[],
  timeframe: PortfolioTimeframe,
  profitableOnly = false,
): TimedActivity[] {
  const bucketMs = portfolioTimeframeMs(timeframe);
  const result: TimedActivity[] = [];
  for (const row of rows || []) {
    const timestamp = finite(row.timestampMs ?? row.timeMs ?? row.executedAt);
    const parsedTimestamp = timestamp ?? Date.parse(String(row.executedAt || ""));
    const side = sideLetter(row.side);
    const pnl = finite(row.realizedPnlUsd) ?? 0;
    if (!side || !Number.isFinite(parsedTimestamp) || parsedTimestamp <= 0) continue;
    if (profitableOnly && pnl <= 0) continue;
    const timeMs = bucketForEvent(parsedTimestamp, candles, bucketMs);
    if (timeMs === null) continue;
    result.push({ timeMs, side, realizedPnlUsd: pnl });
  }
  return result.sort((a, b) => a.timeMs - b.timeMs);
}

export function buildPortfolioTradeMarkers(
  activity: RecentTradeActivity | null | undefined,
  candles: PortfolioEquityCandle[],
  timeframe: PortfolioTimeframe,
): PortfolioChartMarker[] {
  if (!candles.length) return [];
  const interval = portfolioTimeframeMs(timeframe);
  const markers: PortfolioChartMarker[] = [];

  const entries = normalizedActivity(activity?.entries, candles, timeframe, false);
  const entryGroups = new Map<string, TimedActivity[]>();
  for (const event of entries) {
    const key = `${event.timeMs}:${event.side}`;
    const group = entryGroups.get(key) || [];
    group.push(event);
    entryGroups.set(key, group);
  }
  for (const group of entryGroups.values()) {
    const event = group[0];
    const long = event.side === "L";
    markers.push({
      time: Math.floor(event.timeMs / 1000),
      position: long ? "belowBar" : "aboveBar",
      color: long ? "#35ef9a" : "#ff617d",
      shape: long ? "arrowUp" : "arrowDown",
      text: group.length > 1 ? `Entry ${event.side} ×${group.length}` : `Entry ${event.side}`,
      size: 1.35,
      kind: "entry",
    });
  }

  const exits = normalizedActivity(activity?.exits, candles, timeframe, true);
  for (const side of ["L", "S"] as const) {
    const sideEvents = exits.filter((event) => event.side === side);
    const clusters: TimedActivity[][] = [];
    for (const event of sideEvents) {
      const current = clusters.at(-1);
      if (!current || event.timeMs - current.at(-1)!.timeMs > interval * 2) clusters.push([event]);
      else current.push(event);
    }
    for (const cluster of clusters) {
      const uniqueTimes = [...new Set(cluster.map((event) => event.timeMs))];
      for (const timeMs of uniqueTimes) {
        markers.push({
          time: Math.floor(timeMs / 1000),
          position: side === "L" ? "aboveBar" : "belowBar",
          color: side === "L" ? "#35ef9a" : "#ff617d",
          shape: "circle",
          text: "",
          size: 0.65,
          kind: "profit-dot",
        });
      }
      const labelEvent = cluster[Math.floor(cluster.length / 2)];
      markers.push({
        time: Math.floor(labelEvent.timeMs / 1000),
        position: side === "L" ? "aboveBar" : "belowBar",
        color: side === "L" ? "#35ef9a" : "#ff617d",
        shape: "circle",
        text: `💰 ${side} ×${cluster.length}`,
        size: 1.1,
        kind: "profit",
      });
    }
  }

  return markers.sort((a, b) => a.time - b.time || (a.kind === "profit-dot" ? -1 : 1));
}

export function buildPortfolioBollingerMarkers(
  events: PortfolioBollingerEvent[],
  candles: PortfolioEquityCandle[],
  timeframe: PortfolioTimeframe,
): PortfolioChartMarker[] {
  const bucketMs = portfolioTimeframeMs(timeframe);
  return (events || [])
    .filter((event) => event.kind === "bb_upper" || event.kind === "bb_lower")
    .map((event) => {
      const timeMs = bucketForEvent(event.timeMs, candles, bucketMs);
      if (timeMs === null) return null;
      const above = event.kind === "bb_upper";
      return {
        time: Math.floor(timeMs / 1000),
        position: above ? "aboveBar" : "belowBar",
        color: above ? "#ff7890" : "#36f0a0",
        shape: "circle",
        text: formatPortfolioUsd(event.equity),
        size: 0.8,
        kind: "bb",
      } satisfies PortfolioChartMarker;
    })
    .filter((marker): marker is PortfolioChartMarker => marker !== null);
}

export function mergePortfolioMarkers(...groups: PortfolioChartMarker[][]) {
  return groups.flat().sort((a, b) => a.time - b.time || a.kind.localeCompare(b.kind));
}
