import test from "node:test";
import assert from "node:assert/strict";
import { linearPnl, weightedAverage, runBacktest } from "../lib/backtest-engine.ts";

test("hand-calculated LONG and SHORT PnL match exactly", () => {
  assert.equal(linearPnl("LONG", 100, 110, 1), 10);
  assert.equal(linearPnl("SHORT", 100, 90, 1), 10);
  assert.equal(linearPnl("LONG", 100, 90, 1), -10);
});

test("unequal DCA fill sizes produce a quantity-weighted entry", () => {
  assert.equal(weightedAverage([{price:100,quantity:1},{price:80,quantity:1}]),90);
  assert.equal(weightedAverage([{price:100,quantity:1},{price:80,quantity:2}]),260/3);
});

test("A and B runs remain reproducible and isolated", () => {
  const candles = Array.from({length:30},(_,i)=>({time:i+1,open:100,high:103,low:97,close:101}));
  const base = {startingPortfolio:1000,baseNotional:20,leverage:20,takeProfitPct:1,dcaDistancePct:2,maxDca:2,feePct:0.05,slippagePct:0};
  const first=runBacktest(candles,base),again=runBacktest(candles,base),variant=runBacktest(candles,{...base,takeProfitPct:2});
  assert.deepEqual(first,again);
  assert.notDeepEqual(first.trades,variant.trades);
  assert.equal(first.valid,true);
  assert.equal(first.closedTrades,first.trades.length);
});
