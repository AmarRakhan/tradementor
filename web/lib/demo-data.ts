import type { ExchangeId, ExchangeSnapshot } from "./use-exchange-data";

const now = Date.now();
const hoursAgo = (hours: number) => new Date(now - hours * 3_600_000).toISOString();

const closedTrades = [
  { symbol: "BTCUSDT", side: "long", notionalUsd: 84, entryPrice: 118420, exitPrice: 119185, realizedPnlUsd: 0.54, openedAt: hoursAgo(31), closedAt: hoursAgo(26), strategyName: "Dual Profit Harvest", dcaCount: 1 },
  { symbol: "SOLUSDT", side: "short", notionalUsd: 61, entryPrice: 198.42, exitPrice: 196.88, realizedPnlUsd: 0.47, openedAt: hoursAgo(23), closedAt: hoursAgo(19), strategyName: "Dual Profit Harvest", dcaCount: 0 },
  { symbol: "XRPUSDT", side: "long", notionalUsd: 55, entryPrice: 3.124, exitPrice: 3.096, realizedPnlUsd: -0.49, openedAt: hoursAgo(18), closedAt: hoursAgo(14), strategyName: "DCA Pulse", dcaCount: 2 },
  { symbol: "ETHUSDT", side: "long", notionalUsd: 92, entryPrice: 4428.5, exitPrice: 4471.2, realizedPnlUsd: 0.89, openedAt: hoursAgo(12), closedAt: hoursAgo(7), strategyName: "Dual Profit Harvest", dcaCount: 1 },
];

const demo: Record<ExchangeId, Record<string, unknown>> = {
  hyperliquid: {
    portfolioValue: 486.32,
    availableToTrade: 344.58,
    unrealizedPnl: 2.18,
    activePositionCount: 2,
    maintenanceMargin: 6.14,
    unifiedAccountLeverage: 3.2,
    tradingEnabled: false,
    assetPositions: [
      { position: { coin: "BTC", szi: "0.00071", positionValue: "84.77", entryPx: "118420", markPx: "119394", unrealizedPnl: "0.69", leverage: { value: 20 }, openedAt: now - 8 * 3_600_000, strategyName: "DCA Pulse" } },
      { position: { coin: "SOL", szi: "-0.31", positionValue: "61.25", entryPx: "198.42", markPx: "197.58", unrealizedPnl: "0.26", leverage: { value: 15 }, openedAt: now - 5 * 3_600_000, strategyName: "DCA Pulse" } },
    ],
    deals: [
      { symbol: "BTC", safetyOrdersCompleted: 1, lastOrderAt: now - 2 * 3_600_000 },
      { symbol: "SOL", safetyOrdersCompleted: 0, lastOrderAt: now - 5 * 3_600_000 },
    ],
    closedTrades,
    demoData: true,
  },
  aster: {
    configured: true,
    equity: 527.81,
    availableBalance: 376.44,
    unrealizedPnl: 1.63,
    activePositions: 3,
    activeTradeCapital: 18.46,
    maintenanceMargin: 4.22,
    marginRatio: 0.008,
    liveEnabled: false,
    positions: [
      { symbol: "ETHUSDT", side: "long", notionalUsd: 92.4, entryPrice: 4428.5, markPrice: 4471.2, unrealizedPnl: 0.89, leverage: 20, dcaCount: 1, openedAt: hoursAgo(9), lastOrderAt: hoursAgo(3), strategyName: "Dual Profit Harvest" },
      { symbol: "XRPUSDT", side: "short", notionalUsd: 55.2, entryPrice: 3.124, markPrice: 3.096, unrealizedPnl: 0.49, leverage: 20, dcaCount: 0, openedAt: hoursAgo(6), lastOrderAt: hoursAgo(6), strategyName: "Dual Profit Harvest" },
      { symbol: "DOGEUSDT", side: "long", notionalUsd: 41.8, entryPrice: 0.2384, markPrice: 0.2398, unrealizedPnl: 0.25, leverage: 10, dcaCount: 2, openedAt: hoursAgo(15), lastOrderAt: hoursAgo(1), strategyName: "Dual Profit Harvest" },
    ],
    closedTrades,
    historyAvailable: true,
    ordersEnabled: false,
    demoData: true,
  },
};

export const DEMO_MODE_KEY = "tradementor.staging.demoMode.v1";

export function demoModeEnabled(): boolean {
  return typeof window !== "undefined" && window.localStorage.getItem(DEMO_MODE_KEY) === "true";
}

export function demoSnapshot(exchange: ExchangeId): ExchangeSnapshot {
  return { loading: false, data: demo[exchange], error: "", updatedAt: Date.now() };
}
