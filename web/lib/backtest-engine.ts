export type BacktestCandle = { time: number; open: number; high: number; low: number; close: number };
export type BacktestSettings = {
  startingPortfolio: number; baseNotional: number; leverage: number; takeProfitPct: number;
  dcaDistancePct: number; maxDca: number; feePct: number; slippagePct: number;
};
export type BacktestTrade = { side: "LONG" | "SHORT"; entry: number; exit: number; quantity: number; pnl: number; fees: number; openedAt: number; closedAt: number; dcaCount: number };
export type BacktestResult = {
  startingPortfolio: number; endingPortfolio: number; grossPnl: number; netPnl: number; returnPct: number;
  maxDrawdownPct: number; winRatePct: number; profitFactor: number | null; fees: number; closedTrades: number;
  activeTrades: number; dcaOrders: number; maxDcaLayer: number; averageWinner: number; averageLoser: number;
  largestWinner: number; largestLoser: number; equity: Array<{ time: number; value: number }>; trades: BacktestTrade[];
  valid: boolean; assumptions: string[];
};

const money = (value: number) => Math.round((value + Number.EPSILON) * 1e8) / 1e8;
export function weightedAverage(fills: Array<{ price: number; quantity: number }>) {
  const quantity = fills.reduce((sum, fill) => sum + fill.quantity, 0);
  return quantity ? fills.reduce((sum, fill) => sum + fill.price * fill.quantity, 0) / quantity : 0;
}
export function linearPnl(side: "LONG" | "SHORT", entry: number, exit: number, quantity: number) {
  return money((side === "LONG" ? exit - entry : entry - exit) * quantity);
}

export function runBacktest(candles: BacktestCandle[], input: BacktestSettings): BacktestResult {
  const settings = { ...input, startingPortfolio: Math.max(1, input.startingPortfolio), baseNotional: Math.max(1, input.baseNotional), leverage: Math.max(1, input.leverage), maxDca: Math.max(0, Math.floor(input.maxDca)) };
  let balance = settings.startingPortfolio, highWater = balance, maxDrawdown = 0, dcaOrders = 0, maxLayer = 0;
  const trades: BacktestTrade[] = [], equity: Array<{ time: number; value: number }> = [];
  const legs: Record<"LONG" | "SHORT", { fills: Array<{ price: number; quantity: number }>; openedAt: number; dca: number } | null> = { LONG: null, SHORT: null };
  const open = (side: "LONG" | "SHORT", candle: BacktestCandle) => {
    const fillPrice = candle.open * (1 + (side === "LONG" ? 1 : -1) * settings.slippagePct / 100);
    const quantity = settings.baseNotional / fillPrice;
    legs[side] = { fills: [{ price: fillPrice, quantity }], openedAt: candle.time, dca: 0 };
  };
  for (const candle of candles) {
    for (const side of ["LONG", "SHORT"] as const) {
      if (!legs[side]) open(side, candle);
      const leg = legs[side]!;
      let average = weightedAverage(leg.fills);
      const adverse = side === "LONG" ? (average - candle.low) / average * 100 : (candle.high - average) / average * 100;
      if (adverse >= settings.dcaDistancePct && leg.dca < settings.maxDca) {
        const raw = side === "LONG" ? candle.low : candle.high;
        const price = raw * (1 + (side === "LONG" ? 1 : -1) * settings.slippagePct / 100);
        leg.fills.push({ price, quantity: settings.baseNotional / price }); leg.dca += 1; dcaOrders += 1; maxLayer = Math.max(maxLayer, leg.dca); average = weightedAverage(leg.fills);
      }
      const target = side === "LONG" ? average * (1 + settings.takeProfitPct / 100) : average * (1 - settings.takeProfitPct / 100);
      const hit = side === "LONG" ? candle.high >= target : candle.low <= target;
      if (hit) {
        const exit = target * (1 + (side === "LONG" ? -1 : 1) * settings.slippagePct / 100);
        const quantity = leg.fills.reduce((sum, fill) => sum + fill.quantity, 0);
        const gross = linearPnl(side, average, exit, quantity);
        const entryNotional = leg.fills.reduce((sum, fill) => sum + fill.price * fill.quantity, 0);
        const fees = money((entryNotional + exit * quantity) * settings.feePct / 100);
        const pnl = money(gross - fees); balance = money(balance + pnl);
        trades.push({ side, entry: average, exit, quantity, pnl, fees, openedAt: leg.openedAt, closedAt: candle.time, dcaCount: leg.dca });
        legs[side] = null;
      }
    }
    highWater = Math.max(highWater, balance); maxDrawdown = Math.max(maxDrawdown, highWater ? (highWater - balance) / highWater * 100 : 0);
    equity.push({ time: candle.time, value: balance });
  }
  const winners = trades.filter(t => t.pnl > 0), losers = trades.filter(t => t.pnl < 0), grossProfit = winners.reduce((s,t)=>s+t.pnl,0), grossLoss = Math.abs(losers.reduce((s,t)=>s+t.pnl,0));
  const fees = money(trades.reduce((s,t)=>s+t.fees,0)), netPnl = money(balance-settings.startingPortfolio);
  const valid = trades.every(t => Number.isFinite(t.pnl) && t.quantity > 0) && Math.abs(trades.reduce((s,t)=>s+t.pnl,0)-netPnl) < 1e-5;
  return { startingPortfolio:settings.startingPortfolio, endingPortfolio:balance, grossPnl:money(netPnl+fees), netPnl, returnPct:netPnl/settings.startingPortfolio*100, maxDrawdownPct:maxDrawdown, winRatePct:trades.length?winners.length/trades.length*100:0, profitFactor:grossLoss?grossProfit/grossLoss:null, fees, closedTrades:trades.length, activeTrades:Number(Boolean(legs.LONG))+Number(Boolean(legs.SHORT)), dcaOrders, maxDcaLayer:maxLayer, averageWinner:winners.length?grossProfit/winners.length:0, averageLoser:losers.length?-grossLoss/losers.length:0, largestWinner:winners.length?Math.max(...winners.map(t=>t.pnl)):0, largestLoser:losers.length?Math.min(...losers.map(t=>t.pnl)):0, equity, trades, valid, assumptions:["Lineaire USDT-perpetual", "Deterministische slippage", "Conservatieve candlevolgorde: DCA vóór TP", "Geen funding zonder betrouwbare historische fundingdata"] };
}
